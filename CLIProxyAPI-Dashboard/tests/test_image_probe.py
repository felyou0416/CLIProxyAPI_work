import unittest
from unittest.mock import patch

from backend import tools


class ImageProbeTests(unittest.TestCase):
    def test_coc_gpt_image_uses_images_endpoint(self):
        provider_items = [{
            'lookup_provider': 'coc',
            'rows': [{
                'lookup_upstream_id': 'gpt-image-2',
                'upstream_id': 'gpt-image-2',
                'call_id': 'coc-gpt-image',
            }],
        }]

        with patch.object(tools, 'get_configured_provider_models', return_value=provider_items):
            checks = tools._candidate_checks_for_model('coc-gpt-image')

        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['path'], '/v1/images/generations')
        self.assertEqual(checks[0]['payload']['model'], 'coc-gpt-image')

    def test_agnes_video_uses_videos_endpoint(self):
        provider_items = [{
            'lookup_provider': 'agnes',
            'rows': [{
                'lookup_upstream_id': 'agnes-video-v2.0',
                'upstream_id': 'agnes-video-v2.0',
                'call_id': 'agnes-agnes-video-v2.0',
            }],
        }]

        with patch.object(tools, 'get_configured_provider_models', return_value=provider_items):
            checks = tools._candidate_checks_for_model('agnes-agnes-video-v2.0')

        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['path'], '/v1/videos')
        self.assertEqual(checks[0]['payload']['model'], 'agnes-agnes-video-v2.0')


if __name__ == '__main__':
    unittest.main()
