# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch
from wsgiref.util import setup_testing_defaults

from bottle import Bottle

from quasarr.api.arr import setup_arr_routes
from quasarr.downloads.packages import delete_package


class PackageDeleteTests(unittest.TestCase):
    def _shared_state(self):
        shared_state = MagicMock()
        shared_state.get_device.return_value = MagicMock()
        return shared_state

    def test_missing_package_delete_fails_by_default(self):
        shared_state = self._shared_state()

        with (
            patch("quasarr.downloads.packages.JDPackageCache") as cache_cls,
            patch(
                "quasarr.downloads.packages.get_packages",
                return_value={"queue": [], "history": []},
            ) as get_packages,
        ):
            deleted = delete_package(
                shared_state,
                "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef",
            )

        self.assertFalse(deleted)
        cache_cls.assert_called_once_with(shared_state.get_device.return_value)
        get_packages.assert_called_once_with(
            shared_state, _cache=cache_cls.return_value, auto_start=False
        )

    def test_missing_package_delete_can_be_idempotent_for_arr_clients(self):
        shared_state = self._shared_state()

        with (
            patch("quasarr.downloads.packages.JDPackageCache"),
            patch(
                "quasarr.downloads.packages.get_packages",
                return_value={"queue": [], "history": []},
            ),
        ):
            deleted = delete_package(
                shared_state,
                "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef",
                missing_ok=True,
            )

        self.assertTrue(deleted)

    def test_arr_delete_endpoint_treats_missing_package_as_complete(self):
        app = Bottle()
        setup_arr_routes(app)
        package_id = "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef"

        with patch("quasarr.api.arr.delete_package", return_value=True) as delete:
            status, payload = self._call_app(
                app,
                f"mode=queue&name=delete&value={package_id}",
            )

        self.assertEqual("200 OK", status)
        self.assertEqual({"status": True, "nzo_ids": [package_id]}, payload)
        _shared_state, called_package_id = delete.call_args.args
        self.assertEqual(package_id, called_package_id)
        self.assertEqual(
            {"package_title": None, "missing_ok": True},
            delete.call_args.kwargs,
        )

    def _call_app(self, app, query_string):
        environ = {}
        setup_testing_defaults(environ)
        environ.update(
            {
                "REQUEST_METHOD": "GET",
                "PATH_INFO": "/api",
                "QUERY_STRING": query_string,
                "wsgi.input": BytesIO(b""),
            }
        )
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = headers

        body = b"".join(app(environ, start_response)).decode("utf-8")
        return captured["status"], json.loads(body)


if __name__ == "__main__":
    unittest.main()
