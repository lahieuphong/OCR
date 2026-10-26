"""Machine-readable Darwin socket sampling without root or a live macOS host."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import process_network


class ProcessNetworkTest(unittest.TestCase):
    def test_lsof_records_preserve_listener_remote_and_ipv6(self):
        sample = ("p123\nf10\nPTCP\nn127.0.0.1:8765\nTST=LISTEN\n"
                  "f11\nPTCP\nn[::1]:5555->[::1]:8765\nTST=ESTABLISHED\n"
                  "f12\nPUDP\nn*:5353\n")
        sockets = process_network.parse_lsof(sample, 123)
        self.assertEqual(sockets[0].laddr, ("127.0.0.1", 8765))
        self.assertEqual(sockets[0].status, "LISTEN")
        self.assertFalse(sockets[0].raddr)
        self.assertEqual(sockets[1].raddr, ("::1", 8765))
        self.assertEqual(sockets[2].laddr, ("*", 5353))

    def test_lsof_errors_never_become_an_empty_success(self):
        proc = SimpleNamespace(pid=123)
        for result in (SimpleNamespace(returncode=2, stdout="", stderr="permission denied"),
                       SimpleNamespace(returncode=1, stdout="p123\n", stderr=""),
                       SimpleNamespace(returncode=0, stdout="", stderr="warning: incomplete")):
            with self.subTest(result=result), patch.object(process_network.subprocess, "run", return_value=result):
                with self.assertRaises(RuntimeError):
                    process_network.process_connections(proc, platform="darwin")
        with patch.object(process_network.subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                process_network.process_connections(proc, platform="darwin")

    def test_no_matching_sockets_is_valid_but_malformed_records_fail(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="")
        with patch.object(process_network.subprocess, "run", return_value=result) as run:
            self.assertEqual(process_network.process_connections(SimpleNamespace(pid=123), platform="darwin"), [])
            self.assertIn("-a", run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][0], "/usr/sbin/lsof")
        for output in ("p999\n", "p123\nf10\nPTCP\n", "p123\nf10\nPTCP\nnunknown\n"):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                process_network.parse_lsof(output, 123)

    def test_other_platforms_use_per_process_psutil(self):
        process = Mock()
        process.net_connections.return_value = ["socket"]
        self.assertEqual(process_network.process_connections(process, platform="win32"), ["socket"])
        process.net_connections.assert_called_once_with(kind="inet")


if __name__ == "__main__":
    unittest.main()
