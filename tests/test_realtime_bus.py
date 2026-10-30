import asyncio
import threading
import unittest

import app


class RealtimeBusThreads(unittest.TestCase):
    def test_publish_from_worker_thread_wakes_subscriber(self):
        bus = app.RealtimeBus()

        async def scenario():
            q = bus.subscribe(7, asyncio.get_running_loop())
            worker = threading.Thread(target=bus.publish, args=(7, {"type": "ticket"}))
            worker.start()
            data = await asyncio.wait_for(q.get(), timeout=1)
            worker.join()
            bus.unsubscribe(7, q)
            return data

        self.assertEqual(asyncio.run(scenario()), {"type": "ticket"})
        self.assertEqual(bus.subscribers, {})
        self.assertEqual(bus.loops, {})


if __name__ == "__main__":
    unittest.main()
