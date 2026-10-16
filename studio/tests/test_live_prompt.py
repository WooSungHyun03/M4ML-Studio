import unittest
from unittest.mock import patch
import test_state_api as fixtures
from studio.live_prompt import matches


class PromptQueueTests(unittest.TestCase):
    setUp = fixtures.StateAndAPITests.setUp
    tearDown = fixtures.StateAndAPITests.tearDown
    seed_review = fixtures.StateAndAPITests.seed_review

    def test_latest_revision_and_frame_session_guards(self):
        self.seed_review()
        frame = "000001.png"
        session = "test-session"
        r = self.client.post(
            self.url + "/prompt-session",
            headers=self.headers,
            json={"reference": frame, "session_id": session},
        )
        self.assertEqual(r.status_code, 200)
        with patch("studio.live_prompt.schedule"):
            for rev in [1, 2, 5, 4, 3]:
                r = self.client.post(
                    self.url + "/prompt",
                    headers=self.headers,
                    json={
                        "reference": frame,
                        "session_id": session,
                        "prompt_revision": rev,
                        "points": [[5.0, 6.0]],
                        "labels": [1],
                    },
                )
                self.assertEqual(r.status_code, 200)
        p = self.store.get(self.id)
        self.assertEqual(p["live_prompt"]["prompt_revision"], 5)
        self.assertFalse(
            matches(
                p, {"session_id": session, "prompt_revision": 4, "reference": frame}
            )
        )
        self.assertTrue(
            matches(
                p, {"session_id": session, "prompt_revision": 5, "reference": frame}
            )
        )
        r = self.client.post(
            self.url + "/prompt",
            headers=self.headers,
            json={
                "reference": frame,
                "session_id": "old-session",
                "prompt_revision": 9,
            },
        )
        self.assertEqual(r.status_code, 409)

    def test_reset_clears_preview_not_approved_mask(self):
        self.seed_review()
        self.store.update(
            self.id,
            lambda p: p.update(
                preview={"path": "previous.png", "reference": "000001.png"}
            ),
        )
        self.client.post(
            self.url + "/prompt-session",
            headers=self.headers,
            json={"reference": "000001.png", "session_id": "reset"},
        )
        r = self.client.post(
            self.url + "/prompt",
            headers=self.headers,
            json={
                "reference": "000001.png",
                "session_id": "reset",
                "prompt_revision": 1,
                "points": [],
                "labels": [],
            },
        )
        self.assertEqual(r.status_code, 200)
        p = self.store.get(self.id)
        self.assertNotIn("preview", p)
        self.assertEqual(len(p["masks"]), 3)

    def test_cancelled_pending_prompt_cannot_launch_later(self):
        self.seed_review()
        self.client.post(
            self.url + "/prompt-session",
            headers=self.headers,
            json={"reference": "000001.png", "session_id": "cancel-before-start"},
        )
        body = {
            "reference": "000001.png",
            "session_id": "cancel-before-start",
            "prompt_revision": 1,
            "points": [[5.0, 6.0]],
            "labels": [1],
        }
        with patch("studio.live_prompt.schedule"):
            self.client.post(
                self.url + "/prompt", headers=self.headers, json=body
            ).raise_for_status()
        self.client.post(self.url + "/cancel", headers=self.headers).raise_for_status()
        response = self.client.post(
            self.url + "/jobs/preview", headers=self.headers, json=body
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.get(self.id)["live_prompt"]["status"], "cancelled")
        self.assertIsNone(self.store.active(self.id))

    def test_nonfinite_prompt_cannot_poison_persistent_project_json(self):
        self.seed_review()
        self.client.post(
            self.url + "/prompt-session",
            headers=self.headers,
            json={"reference": "000001.png", "session_id": "finite"},
        )
        response = self.client.post(
            self.url + "/prompt",
            headers={**self.headers, "content-type": "application/json"},
            content='{"reference":"000001.png","session_id":"finite","prompt_revision":1,"points":[[NaN,1]],"labels":[1]}',
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.store.get(self.id)["live_prompt"]["prompt_revision"], 0)

class PreviewRetentionTests(unittest.TestCase):
    def test_superseded_predictions_cannot_delete_the_published_recovery_mask(self):
        import tempfile
        from pathlib import Path
        from studio.live_prompt import cleanup_previews
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); folder=root/'live/session'
            for revision in range(1,7):
                item=folder/f'{revision:06d}'
                item.mkdir(parents=True)
                (item/'mask.png').write_bytes(fixtures.png(255,mode='L'))
            published=folder/'000001/mask.png'; original=published.read_bytes()
            cleanup_previews(root,folder,str(published.relative_to(root)))
            self.assertEqual(published.read_bytes(),original)
            self.assertEqual({p.name for p in folder.iterdir()},{'000001','000004','000005','000006'})
            # Only after another real result is published may the old file expire.
            cleanup_previews(root,folder,'live/session/000006/mask.png')
            self.assertEqual({p.name for p in folder.iterdir()},{'000004','000005','000006'})
