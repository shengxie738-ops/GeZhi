"""Guarded production-source parser tests, not ASGI/SQL/provider integration.

Only allowlisted function/constant AST nodes execute; application imports never
execute. HTTPException is a recording port. Socket/network operations are denied.
"""
import ast
import math
from pathlib import Path
import re
import socket
import unittest
from unittest.mock import patch
from urllib.parse import quote, unquote, urlsplit


SOURCE = Path(__file__).resolve().parents[1] / 'app/services/academic_sources.py'


class SourceHTTPException(Exception):
    def __init__(self, status_code, detail, headers=None):
        self.status_code, self.detail, self.headers = status_code, detail, headers


def load_parser():
    functions = {'_source_error', 'normalize_doi_query', 'normalize_arxiv_identifier',
                 'sanitize_academic_search_query', 'plan_academic_query',
                 '_valid_arxiv_advanced', 'compile_arxiv_query'}
    constants = {'MAX_EFFECTIVE_QUERY_LENGTH', 'DOI_REGEX', 'BACKEND_TERM_TRANSLATIONS', '_ARXIV_FIELDS'}
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in functions
             or isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in constants for target in node.targets)]
    assert {node.name for node in nodes if isinstance(node, ast.FunctionDef)} == functions
    namespace = {'re': re, 'math': math, 'quote': quote, 'unquote': unquote, 'urlsplit': urlsplit,
                 'HTTPException': SourceHTTPException}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


class AcademicParserBoundsSourceTests(unittest.TestCase):
    def setUp(self):
        self.guards = [patch.object(socket, name, side_effect=AssertionError('Network forbidden in source-only parser tests'))
                       for name in ('socket', 'create_connection')]
        for guard in self.guards:
            guard.start()
            self.addCleanup(guard.stop)
        self.parser = load_parser()

    def test_allowed_depth_and_token_boundaries_preserve_exact_advanced_syntax(self):
        queries = ['(' * 32 + 'ti:transformer' + ')' * 32,
                   '(' + ' AND '.join(['ti:x'] * 85) + ')',
                   'ti:"deep learning" AND submittedDate:[20200101 TO 20241231]']
        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(self.parser['_valid_arxiv_advanced'](query))
                self.assertEqual(self.parser['compile_arxiv_query'](query), query)

    def test_excessive_advanced_depth_and_tokens_are_structured_validation_errors(self):
        queries = ['(' * 33 + 'ti:transformer' + ')' * 33,
                   ' AND '.join(['ti:x'] * 86),
                   '(' * 600 + 'ti:transformer' + ')' * 600]
        for query in queries:
            for source in ('arxiv', 'crossref', 'openalex'):
                with self.subTest(length=len(query), source=source):
                    with self.assertRaises(SourceHTTPException) as error:
                        self.parser['plan_academic_query'](query, source)
                    self.assertEqual(error.exception.status_code, 422)
                    self.assertEqual(error.exception.detail['code'], 'invalid_query')

    def test_long_plain_and_quoted_queries_do_not_become_advanced_syntax(self):
        for query in (' '.join(['word'] * 300), ' '.join(['"ti:literal"'] * 270),
                      ' '.join(['word'] * 257) + ' ti:label',
                      "'" + ' '.join(['word'] * 257) + " ti:literal'",
                      "'" + '(' * 600 + "ti:literal" + ')' * 600 + "'"):
            with self.subTest(query=query[:40]):
                self.assertFalse(self.parser['_valid_arxiv_advanced'](query))
                self.assertEqual(self.parser['plan_academic_query'](query, 'crossref')['effectiveQuery'], query)

    def test_malformed_nesting_stays_bounded_without_changing_plain_query_behavior(self):
        for query in ('(ti:foo', 'ti:foo)', '(' * 600 + 'ordinary' + ')' * 600):
            self.assertFalse(self.parser['_valid_arxiv_advanced'](query))


if __name__ == '__main__':
    unittest.main()
