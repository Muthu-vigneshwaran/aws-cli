# Copyright 2013 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
import mock
from awscli.compat import six
from awscli.testutils import unittest, FileCreator
from awscli.testutils import skip_if_windows

from awscli.paramfile import get_paramfile, ResourceLoadingError
from awscli.paramfile import UriArgumentHandler
from awscli.paramfile import LOCAL_PREFIX_MAP, REMOTE_PREFIX_MAP
from awscli.paramfile import register_uri_param_handler
from botocore.hooks import HierarchicalEmitter


class FakeSession(object):
    def __init__(self, config, emitter=None):
        self.config = config
        if emitter is None:
            emitter = HierarchicalEmitter()
        self.emitter = emitter

    def register(self, event_name, handler):
        self.emitter.register(event_name, handler)

    def emit(self, event_name, **kwargs):
        return self.emitter.emit(event_name, **kwargs)

    def get_scoped_config(self):
        return self.config


class TestUriArgumentHandler(unittest.TestCase):
    def test_default_does_have_local_and_remote(self):
        with mock.patch(
                'awscli.paramfile.get_paramfile') as mock_get_paramfile:
            handler = UriArgumentHandler()
            handler('event-name', 'param', 'value')
            prefixes = mock_get_paramfile.call_args[0][1]

        self.assertEqual(len(prefixes), 4)
        self.assertIn('file://', prefixes)
        self.assertIn('fileb://', prefixes)
        self.assertIn('http://', prefixes)
        self.assertIn('https://', prefixes)

    def test_uses_supplied_cases(self):
        with mock.patch(
                'awscli.paramfile.get_paramfile') as mock_get_paramfile:
            handler = UriArgumentHandler({'foo': None, 'bar': None})
            handler('event-name', 'param', 'value')
            prefixes = mock_get_paramfile.call_args[0][1]

        self.assertEqual(len(prefixes), 2)
        self.assertIn('foo', prefixes)
        self.assertIn('bar', prefixes)

    def test_does_use_all_prefixes_when_enabled(self):
        session = FakeSession({"cli_follow_urlparam": "true"})
        register_uri_param_handler(session)
        with mock.patch(
                'awscli.paramfile.get_paramfile') as mock_get_paramfile:
            session.emit('load-cli-arg.service.operation.arg', param='foo', value='bar')
            prefixes = mock_get_paramfile.call_args[0][1]

        self.assertEqual(len(prefixes), 4)
        self.assertIn('file://', prefixes)
        self.assertIn('fileb://', prefixes)
        self.assertIn('http://', prefixes)
        self.assertIn('https://', prefixes)

    def test_does_use_all_prefixes_when_not_set(self):
        session = FakeSession({})
        register_uri_param_handler(session)
        with mock.patch(
                'awscli.paramfile.get_paramfile') as mock_get_paramfile:
            session.emit('load-cli-arg.service.operation.arg', param='foo', value='bar')
            prefixes = mock_get_paramfile.call_args[0][1]

        self.assertEqual(len(prefixes), 4)
        self.assertIn('file://', prefixes)
        self.assertIn('fileb://', prefixes)
        self.assertIn('http://', prefixes)
        self.assertIn('https://', prefixes)

    def test_does_not_use_http_prefixes_when_disabled(self):
        session = FakeSession({"cli_follow_urlparam": "false"})
        register_uri_param_handler(session)
        with mock.patch(
                'awscli.paramfile.get_paramfile') as mock_get_paramfile:
            session.emit('load-cli-arg.service.operation.arg', param='foo', value='bar')
            prefixes = mock_get_paramfile.call_args[0][1]

        self.assertEqual(len(prefixes), 2)
        self.assertIn('file://', prefixes)
        self.assertIn('fileb://', prefixes)


class TestParamFile(unittest.TestCase):
    def setUp(self):
        self.files = FileCreator()

    def tearDown(self):
        self.files.remove_all()

    def get_paramfile(self, path):
        return get_paramfile(path, LOCAL_PREFIX_MAP.copy())

    def test_text_file(self):
        contents = 'This is a test'
        filename = self.files.create_file('foo', contents)
        prefixed_filename = 'file://' + filename
        data = self.get_paramfile(prefixed_filename)
        self.assertEqual(data, contents)
        self.assertIsInstance(data, six.string_types)

    def test_binary_file(self):
        contents = 'This is a test'
        filename = self.files.create_file('foo', contents)
        prefixed_filename = 'fileb://' + filename
        data = self.get_paramfile(prefixed_filename)
        self.assertEqual(data, b'This is a test')
        self.assertIsInstance(data, six.binary_type)

    @skip_if_windows('Binary content error only occurs '
                     'on non-Windows platforms.')
    def test_cannot_load_text_file(self):
        contents = b'\xbfX\xac\xbe'
        filename = self.files.create_file('foo', contents, mode='wb')
        prefixed_filename = 'file://' + filename
        with self.assertRaises(ResourceLoadingError):
            self.get_paramfile(prefixed_filename)

    def test_file_does_not_exist_raises_error(self):
        with self.assertRaises(ResourceLoadingError):
            self.get_paramfile('file://file/does/not/existsasdf.txt')

    def test_no_match_uris_returns_none(self):
        self.assertIsNone(self.get_paramfile('foobar://somewhere.bar'))

    def test_non_string_type_returns_none(self):
        self.assertIsNone(self.get_paramfile(100))


class TestHTTPBasedResourceLoading(unittest.TestCase):
    def setUp(self):
        self.requests_patch = mock.patch('awscli.paramfile.requests')
        self.requests_mock = self.requests_patch.start()
        self.response = mock.Mock(status_code=200)
        self.requests_mock.get.return_value = self.response

    def tearDown(self):
        self.requests_patch.stop()

    def get_paramfile(self, path):
        return get_paramfile(path, REMOTE_PREFIX_MAP.copy())

    def test_resource_from_http(self):
        self.response.text = 'http contents'
        loaded = self.get_paramfile('http://foo.bar.baz')
        self.assertEqual(loaded, 'http contents')
        self.requests_mock.get.assert_called_with('http://foo.bar.baz')

    def test_resource_from_https(self):
        self.response.text = 'http contents'
        loaded = self.get_paramfile('https://foo.bar.baz')
        self.assertEqual(loaded, 'http contents')
        self.requests_mock.get.assert_called_with('https://foo.bar.baz')

    def test_non_200_raises_error(self):
        self.response.status_code = 500
        with self.assertRaisesRegexp(ResourceLoadingError, 'foo\.bar\.baz'):
            self.get_paramfile('https://foo.bar.baz')

    def test_connection_error_raises_error(self):
        self.requests_mock.get.side_effect = Exception("Connection error.")
        with self.assertRaisesRegexp(ResourceLoadingError, 'foo\.bar\.baz'):
            self.get_paramfile('https://foo.bar.baz')
