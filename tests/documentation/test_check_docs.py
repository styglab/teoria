"""Regression cases for documentation failures that must block CI."""
from pathlib import Path
import tempfile
import unittest

from tests.documentation.check_docs import validate


class DocumentationChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'docs').mkdir()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    def test_valid_unicode_fragment_duplicate_heading_and_reference_link(self):
        self.write('docs/index.md', '[guide][g]\n\n[g]: guide.md#실행-설정-1\n')
        self.write('docs/guide.md', '# 실행 설정\n\n## 실행 설정\n')
        self.assertEqual(validate(self.root)[0], [])

    def test_missing_file_reports_source_and_line(self):
        self.write('docs/index.md', '# Docs\n\n[missing](removed.md)\n')
        self.assertIn('docs/index.md:3: missing target: removed.md', validate(self.root)[0])

    def test_changed_heading_is_rejected_even_when_file_exists(self):
        self.write('docs/index.md', '[guide](guide.md#old-name)\n')
        self.write('docs/guide.md', '# New name\n')
        self.assertTrue(any('missing heading' in error for error in validate(self.root)[0]))

    def test_unlinked_document_is_reported(self):
        self.write('docs/index.md', '# Docs\n')
        self.write('docs/orphan.md', '# Orphan\n')
        self.assertIn('docs/orphan.md: unreachable from docs/index.md', validate(self.root)[0])

    def test_code_examples_and_external_links_do_not_require_local_files(self):
        self.write('docs/index.md', '''# Docs
[site](https://example.invalid/)
`[example](missing.md)`
```markdown
[example](also_missing.md)
```
''')
        self.assertEqual(validate(self.root)[0], [])

    def test_directory_path_image_and_transitive_navigation(self):
        self.write('docs/index.md', '[guide](guide.md)\n')
        self.write('docs/guide.md', '[detail](detail.md)\n![image](assets/a.svg)\n')
        self.write('docs/detail.md', '# Detail\n')
        self.write('docs/assets/a.svg', '<svg/>')
        self.assertEqual(validate(self.root)[0], [])

    def test_undefined_reference_is_reported(self):
        self.write('docs/index.md', '[guide][missing]\n')
        self.assertTrue(any('undefined link reference' in error for error in validate(self.root)[0]))


if __name__ == '__main__':
    unittest.main()
