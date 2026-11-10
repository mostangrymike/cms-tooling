"""Offline guards for the capability policy table.

These tests do not touch a terminal or a network. They assert that the one
capability set, the reviewed tool inventory, and the MCP server registration
cannot drift apart.
"""
import asyncio
import dataclasses
import unittest

import cms_policy
from cms_mcp import Session, create_server


class CapabilityTests(unittest.TestCase):
    def test_every_capability_has_a_flag_and_a_field(self):
        self.assertEqual(set(cms_policy.CAPABILITY_FLAGS),
                         {f.name for f in dataclasses.fields(cms_policy.Capabilities)})

    def test_from_flags_rejects_unknown_flags(self):
        with self.assertRaises(TypeError):
            cms_policy.Capabilities.from_flags({"allow_teleport": True})

    def test_from_flags_maps_named_flags(self):
        caps = cms_policy.Capabilities.from_flags(
            {"allow_downloads": True, "allow_commands": 1})
        self.assertTrue(caps.downloads)
        self.assertTrue(caps.commands)
        self.assertFalse(caps.uploads)

    def test_capabilities_are_frozen(self):
        caps = cms_policy.Capabilities()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            caps.downloads = True

    def test_session_shim_reads_one_object(self):
        session = Session(allow_downloads=True)
        self.assertTrue(session.caps.downloads)
        session.allow_downloads = False
        self.assertFalse(session.caps.downloads)
        self.assertFalse(session.allow_downloads)

    def test_session_rejects_mixed_construction(self):
        with self.assertRaises(TypeError):
            Session(capabilities=cms_policy.Capabilities(), allow_input=True)

    def test_declarations_name_known_capabilities(self):
        for spec in cms_policy.TOOL_DECLARATIONS:
            for name in spec.requires:
                self.assertIn(name, cms_policy.CAPABILITY_FLAGS, spec.name)


class RefusalTests(unittest.TestCase):
    def test_refusal_names_every_missing_flag(self):
        refused = cms_policy.refusal(cms_policy.declaration("cms_download"),
                                     cms_policy.Capabilities())
        self.assertFalse(refused["ok"])
        self.assertIn("--allow-downloads", refused["message"])
        self.assertIn("--allow-commands", refused["message"])

    def test_refusal_keeps_the_tool_structured_fields(self):
        refused = cms_policy.refusal(cms_policy.declaration("cms_query_links"),
                                     cms_policy.Capabilities())
        self.assertIs(refused["replacement_safe"], False)

    def test_enabled_tool_has_no_refusal(self):
        caps = cms_policy.Capabilities(downloads=True, commands=True)
        self.assertIsNone(cms_policy.refusal(cms_policy.declaration("cms_download"), caps))


class RegistrationTests(unittest.TestCase):
    def test_declared_inventory_matches_registered_tools(self):
        server = create_server(Session())
        names = {tool.name for tool in asyncio.run(server.list_tools())}
        self.assertEqual(names, set(cms_policy.TOOL_CAPABILITIES))

    def test_undeclared_tool_is_rejected_at_registration(self):
        with self.assertRaises(RuntimeError):
            cms_policy.declaration("cms_teleport")


if __name__ == "__main__":
    unittest.main()
