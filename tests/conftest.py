"""Integration fixture: builds the real server, starts Postgres behind PgBouncer, runs it.

The server source comes from SCORM_DISPATCH_SRC (default ../scorm-dispatch). Integration tests
FAIL, never skip, when it is missing: `make integration` must not go green without a server.
"""

import os
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest
import pytest_asyncio
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.postgres import PostgresContainer

from scorm_dispatch import Client

ROOT = Path(__file__).parent.parent
ADMIN_KEY = "integration-admin-key"
MAX_PACKAGE_BYTES = 20_000
LEARNER_RATE = 5


@dataclass(frozen=True)
class Server:
    base_url: str


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _postgres_with_bouncer(network: Network) -> Iterator[tuple[str, str]]:
    with (
        PostgresContainer(
            "postgres:17-alpine", username="scorm", password="scorm", dbname="scorm", driver=None
        )
        .with_network(network)
        .with_network_aliases("postgres") as pg,
        DockerContainer("edoburu/pgbouncer:v1.25.1-p0")
        .with_env("DB_HOST", "postgres")
        .with_env("DB_NAME", "scorm")
        .with_env("DB_USER", "scorm")
        .with_env("DB_PASSWORD", "scorm")
        .with_env("POOL_MODE", "transaction")
        .with_env("AUTH_TYPE", "scram-sha-256")
        .with_env("LISTEN_PORT", "6432")
        .with_exposed_ports(6432)
        .with_network(network)
        .with_network_aliases("pgbouncer") as bouncer,
    ):
        wait_for_logs(bouncer, "process up", timeout=120)
        direct = pg.get_connection_url()
        via = (
            f"postgres://scorm:scorm@{bouncer.get_container_host_ip()}:"
            f"{bouncer.get_exposed_port(6432)}/scorm?sslmode=disable"
        )
        yield direct, via


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Server]:
    src = Path(os.environ.get("SCORM_DISPATCH_SRC", ROOT.parent / "scorm-dispatch")).resolve()
    if not (src / "cmd" / "scorm-dispatch").is_dir():
        pytest.fail(f"server source not found at {src}: set SCORM_DISPATCH_SRC", pytrace=False)

    binary = tmp_path_factory.mktemp("bin") / "scorm-dispatch"
    subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/scorm-dispatch"],
        cwd=src,
        check=True,
        env={**os.environ, "CGO_ENABLED": "0"},
    )

    with Network() as network:
        chunks = _postgres_with_bouncer(network)
        direct, via = next(chunks)
        minio = (
            DockerContainer("bitnamilegacy/minio:2025.7.23")
            .with_env("MINIO_ROOT_USER", "minio")
            .with_env("MINIO_ROOT_PASSWORD", "minio-secret")
            .with_exposed_ports(9000)
            .start()
        )
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "DATABASE_URL": via,
            "DATABASE_MIGRATIONS_URL": direct.replace(
                "postgresql+psycopg2://", "postgres://"
            ).replace("postgresql://", "postgres://"),
            "ADMIN_API_KEY": ADMIN_KEY,
            "PUBLIC_BASE_URL": base,
            "LISTEN_ADDR": f"127.0.0.1:{port}",
            "MAX_PACKAGE_BYTES": str(MAX_PACKAGE_BYTES),
            "RATE_LIMIT_LEARNER_PER_MINUTE": str(LEARNER_RATE),
            # Stream tokens are signed locally; s3:// presigning asks MinIO for the bucket region.
            "STREAM_LIBRARY_ID": "1",
            "STREAM_TOKEN_KEY": "stream-token-key",
            "S3_ENDPOINT": f"http://{minio.get_container_host_ip()}:{minio.get_exposed_port(9000)}",
            "S3_ACCESS_KEY": "minio",
            "S3_SECRET_KEY": "minio-secret",
            "S3_REGION": "us-east-1",
        }
        wait_for_logs(minio, "API:", timeout=60)
        minio.exec("mkdir -p /data/bucket")  # a directory in the data dir is a bucket
        subprocess.run([str(binary), "migrate"], env=env, check=True, timeout=120)
        proc = subprocess.Popen([str(binary), "serve"], env=env)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    if httpx2.get(base + "/healthz").status_code == 200:
                        break
                except httpx2.TransportError:
                    pass
                if proc.poll() is not None or time.monotonic() > deadline:
                    pytest.fail("server did not become healthy", pytrace=False)
                time.sleep(0.2)
            yield Server(base)
        finally:
            proc.terminate()  # only the PID this fixture started
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            minio.stop()
            chunks.close()  # leaves the container context managers: removes both containers


@pytest_asyncio.fixture
async def client(server: Server) -> AsyncIterator[Client]:
    async with Client(server.base_url, ADMIN_KEY) as c:
        yield c
