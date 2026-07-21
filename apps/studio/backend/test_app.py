import os
import unittest
from unittest.mock import patch

from app import app


class MutationAuthenticationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def post_validation(self, **kwargs):
        return self.client.post(
            '/api/validate-headings',
            json={'content': '# Title'},
            **kwargs,
        )

    def test_mutations_fail_closed_without_auth_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.post_validation()

        self.assertEqual(response.status_code, 401)

    def test_editor_mode_only_bypasses_auth_for_loopback_requests(self):
        with patch.dict(os.environ, {'EDITOR_MODE': 'true'}, clear=True):
            local_response = self.post_validation(
                environ_base={'REMOTE_ADDR': '127.0.0.1'}
            )
            remote_response = self.post_validation(
                environ_base={'REMOTE_ADDR': '203.0.113.10'}
            )

        self.assertEqual(local_response.status_code, 200)
        self.assertEqual(remote_response.status_code, 401)

    def test_valid_bearer_token_allows_remote_mutation(self):
        with patch.dict(
            os.environ,
            {'STUDIO_AUTH_TOKEN': 'expected-token'},
            clear=True,
        ):
            response = self.post_validation(
                headers={'Authorization': 'Bearer expected-token'},
                environ_base={'REMOTE_ADDR': '203.0.113.10'},
            )

        self.assertEqual(response.status_code, 200)

    def test_invalid_bearer_token_is_rejected(self):
        with patch.dict(
            os.environ,
            {'STUDIO_AUTH_TOKEN': 'expected-token'},
            clear=True,
        ):
            response = self.post_validation(
                headers={'Authorization': 'Bearer wrong-token'},
                environ_base={'REMOTE_ADDR': '203.0.113.10'},
            )

        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main()
