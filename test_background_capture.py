import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from background_capture import read_page_text


class BackgroundCaptureTests(unittest.TestCase):
    def test_read_uses_only_evaluate_and_frames(self):
        main=object()
        child=SimpleNamespace(evaluate=Mock(return_value='frame TSV'))
        page=SimpleNamespace(evaluate=Mock(return_value='page TSV'),frames=[main,child],main_frame=main)
        self.assertEqual(read_page_text(page),'page TSV\n\nframe TSV')
        page.evaluate.assert_called_once()
        child.evaluate.assert_called_once()

    def test_cancel_does_not_read_page(self):
        page=SimpleNamespace(evaluate=Mock())
        with self.assertRaises(InterruptedError):
            read_page_text(page,lambda:True)
        page.evaluate.assert_not_called()


if __name__=='__main__': unittest.main()
