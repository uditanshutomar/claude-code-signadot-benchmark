import importlib.util, pathlib, socket, threading, unittest

spec = importlib.util.spec_from_file_location('local_tunnel', pathlib.Path(__file__).with_name('local-tunnel.py'))
local_tunnel = importlib.util.module_from_spec(spec); spec.loader.exec_module(local_tunnel)

def server(reply):
    s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1)
    def serve():
        conn, _ = s.accept(); conn.recv(3)
        if reply: conn.sendall(reply)
        threading.Event().wait(5); conn.close()
    threading.Thread(target=serve, daemon=True).start()
    return s.getsockname()[1]

class HealthTests(unittest.TestCase):
    def test_answering_socks_proxy_is_healthy(self):
        self.assertTrue(local_tunnel.healthy(server(b'\x05\x00')))
    def test_forward_that_accepts_but_never_answers_is_not(self):
        # A degraded kubectl port-forward accepts the TCP connection but its stream to the pod times out.
        self.assertFalse(local_tunnel.healthy(server(None), timeout=1))
    def test_closed_port_is_not(self):
        s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
        self.assertFalse(local_tunnel.healthy(port, timeout=1))

if __name__ == '__main__': unittest.main()
