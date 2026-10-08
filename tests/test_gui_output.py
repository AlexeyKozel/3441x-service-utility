"""Exercise worker output events without opening a Tk window."""
import json
from pathlib import Path
import queue
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utility3441x.gui import ServiceUtilityGui


class GuiOutputTests(unittest.TestCase):
    def output_for(self, result):
        state = SimpleNamespace(_busy=False, events=queue.Queue())
        ServiceUtilityGui._run_worker(state, 'Offline test', lambda: result)
        events = []
        while True:
            event = state.events.get(timeout=5)
            events.append(event)
            if event[0] == 'done':
                self.assertTrue(event[1]['success'])
                break
        return events

    def test_cli_json_text_is_displayed_once_without_string_escaping(self):
        text = json.dumps({'value': 1, 'note': 'x − y', 'path': r'C:\cal.bin'},
                          indent=2, ensure_ascii=False)
        events = self.output_for(text)
        output = [value for kind, value in events if kind == 'output']
        self.assertEqual(output, [text])
        self.assertIsInstance(json.loads(output[0]), dict)
        self.assertIn('\n  "value":', output[0])

    def test_structured_result_and_warning_still_render(self):
        result = {'warning': 'Check source', 'value': 2}
        events = self.output_for(result)
        text = next(value for kind, value in events if kind == 'output')
        self.assertEqual(json.loads(text), result)
        self.assertIn(('warning', 'Check source'), events)


if __name__ == '__main__':
    unittest.main()
