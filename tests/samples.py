"""Valid bodies shared by the unit and contract tests."""

from scorm_dispatch.models import Course, PartnerInput

PARTNER_IN: PartnerInput = {
    "name": "Northwind Academy",
    "contactEmail": "learning@northwind.example",
    "seatCap": 500,
    "allowedOrigins": ["https://lms.northwind.example"],
    "active": True,
}
PARTNER_OUT = {
    **PARTNER_IN,
    "partnerId": "northwind",
    "createdAt": "2026-11-01T09:30:00Z",
    "updatedAt": "2026-11-01T09:30:00Z",
}
ASSET_OUT = {
    "assetKey": "vid-walkthrough",
    "assetId": "Zk3p9QwL7xYb2NcVd8TfRa",
    "kind": "video",
    "uri": "stream-bunny://6f1c2a9e-5b7d-4c0e-9a41-2d8f3b7e1a55",
    "createdAt": "2026-11-01T09:30:00Z",
    "updatedAt": "2026-11-01T09:30:00Z",
}
RUNTIME_OUT = {
    "kind": "video",
    "url": "https://media.example.com/embed/6f1c?token=0a&expires=1793527200",
    "expiresAt": "2026-11-01T10:05:00Z",
}
REPORT_OUT = {
    "month": "2026-11",
    "partners": [
        {
            "partnerId": "northwind",
            "name": "Northwind Academy",
            "seatCap": 500,
            "activeLearners": 312,
            "rejectedOrigins": [{"origin": "https://unknown.example", "count": 4}],
        }
    ],
}
COURSE: Course = {
    "id": "intro-to-safety",
    "title": "Introduction to workplace safety",
    "version": "3",
    "language": "en",
    "modules": [
        {
            "title": "Getting started",
            "lessons": [
                {"id": "l1", "title": "Welcome", "type": "text", "html": "<p>Welcome.</p>"},
                {
                    "id": "l2",
                    "title": "Walkthrough",
                    "type": "video",
                    "assetKey": "vid-walkthrough",
                },
                {
                    "id": "l3",
                    "title": "Checklist",
                    "type": "file",
                    "assetKey": "pdf-checklist",
                    "fileName": "checklist.pdf",
                },
                {
                    "id": "l4",
                    "title": "Final exam",
                    "type": "quiz",
                    "quiz": {
                        "final": True,
                        "passingScore": 70,
                        "questions": [
                            {
                                "id": "q1",
                                "type": "single",
                                "promptHtml": "<p>Where?</p>",
                                "options": [
                                    {"id": "a", "html": "Car park"},
                                    {"id": "b", "html": "Lobby"},
                                ],
                                "correct": ["a"],
                            }
                        ],
                    },
                },
            ],
        }
    ],
}
PROBLEM_422 = {
    "type": "about:blank",
    "title": "Unprocessable Content",
    "status": 422,
    "detail": "The course has 1 problem.",
    "errors": [{"path": "course.modules[0].lessons[1].assetKey", "message": "not registered"}],
}
