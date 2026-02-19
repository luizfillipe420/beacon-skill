import unittest
from unittest import mock

from beacon_skill.transports.discord import DiscordClient, DiscordError


class _Resp:
    def __init__(self, status_code=204, text="", data=None):
        self.status_code = status_code
        self.text = text
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class TestDiscordTransport(unittest.TestCase):
    def test_send_message_success_204(self) -> None:
        client = DiscordClient(webhook_url="https://discord.invalid/webhook")
        with mock.patch.object(client.session, "post", return_value=_Resp(status_code=204, text="")) as post:
            result = client.send_message("hello")
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], 204)
            args, kwargs = post.call_args
            self.assertEqual(args[0], "https://discord.invalid/webhook")
            self.assertIn("json", kwargs)
            self.assertEqual(kwargs["json"]["content"], "hello")

    def test_send_beacon_includes_embed_fields(self) -> None:
        client = DiscordClient(webhook_url="https://discord.invalid/webhook")
        with mock.patch.object(client.session, "post", return_value=_Resp(status_code=200, text='{"ok":true}', data={"id": "1"})) as post:
            result = client.send_beacon(
                content="hello world",
                kind="bounty",
                agent_id="bcn_abcdef123456",
                rtc_tip=7.5,
                signature_preview="abc123",
            )
            self.assertTrue(result["ok"])
            payload = post.call_args.kwargs["json"]
            self.assertIn("embeds", payload)
            embed = payload["embeds"][0]
            self.assertEqual(embed["title"], "Beacon Ping · BOUNTY")
            field_names = [f["name"] for f in embed["fields"]]
            self.assertIn("RTC Tip", field_names)
            self.assertIn("Signature", field_names)

    def test_send_without_webhook_errors(self) -> None:
        client = DiscordClient(webhook_url="")
        with self.assertRaises(DiscordError):
            client.send_message("hi")


if __name__ == "__main__":
    unittest.main()
