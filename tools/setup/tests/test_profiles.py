"""Tests for the role reader and for resolving a role's profile
(wfsetup.roles, wfsetup.profiles), and for ``show roles``.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import support
from wfsetup import profiles, roles, tomlio
from wfsetup.errors import SetupError

DEFINITIONS = ["coder", "coder-hard", "manager", "product-manager"]

# The fixture roles on the fixture dictionaries, nothing overridden.
DEFAULTS = {
    ("coder", "claude-code"): ("sonnet", "medium"),
    ("coder", "codex"): ("gpt-6.1-sol", "medium"),
    ("coder-hard", "claude-code"): ("opus", "high"),
    ("coder-hard", "codex"): ("gpt-6.1-sol", "high"),
    ("manager", "claude-code"): ("sonnet", "medium"),
    ("manager", "codex"): ("gpt-6.1-sol", "medium"),
    ("product-manager", "claude-code"): ("opus", "high"),
    ("product-manager", "codex"): ("gpt-6.1-sol", "high"),
}


class FixtureCase(support.ScratchCase):
    """The fixture roles and dictionaries of the fake clone, with scratch settings."""

    def all(self, project: bool = True) -> dict:
        found = profiles.resolve_all(self.locations(project))
        return {(item.definition, item.provider): item for item in found}

    def one(self, definition: str, provider: str) -> profiles.Resolved:
        return profiles.resolve(self.locations(), definition, provider)

    def values(self) -> dict:
        return {key: (item.model, item.effort) for key, item in self.all().items()}

    def error(self) -> list[str]:
        with self.assertRaises(SetupError) as caught:
            profiles.resolve_all(self.locations())
        return caught.exception.lines


class DefaultResolutionTests(FixtureCase):
    def test_the_four_definitions_on_both_providers(self) -> None:
        self.assertEqual(self.values(), DEFAULTS)

    def test_the_order_is_by_definition_then_provider(self) -> None:
        self.assertEqual(list(self.all()), list(DEFAULTS))
        self.assertEqual([item.id for item in roles.definitions(self.locations())], DEFINITIONS)

    def test_every_default_is_decided_by_the_role_file(self) -> None:
        for key, item in self.all().items():
            with self.subTest(key=key):
                self.assertEqual((item.model_layer, item.effort_layer), ("role", "role"))
                self.assertEqual((item.tier.layer, item.effort_name.layer), ("role", "role"))
                self.assertEqual(item.tier.file, self.roles_dir / item.role / "role.toml")
                self.assertEqual((item.model_from.layer, item.effort_from.layer), ("shipped", "shipped"))
                self.assertFalse(item.explicit_model)
                self.assertEqual(item.notes, ())

    def test_the_sources_name_their_keys(self) -> None:
        normal, hard = self.one("coder", "codex"), self.one("coder-hard", "codex")
        self.assertEqual((normal.role, hard.role), ("coder", "coder"))
        self.assertEqual((normal.tier.key, normal.tier.value), ("profile.tier", "standard"))
        self.assertEqual((hard.tier.key, hard.tier.value), ("profile.hard.tier", "deep"))
        self.assertEqual((hard.effort_name.key, hard.effort_name.value), ("profile.hard.effort", "high"))
        self.assertEqual(normal.model_from.key, "providers.codex.tiers.standard")
        self.assertEqual(normal.model_from.file, self.codex_dictionary)
        self.assertEqual(hard.effort_from.key, "providers.codex.efforts.high")

    def test_a_definition_or_provider_that_does_not_exist(self) -> None:
        with self.assertRaises(SetupError) as caught:
            self.one("architect", "codex")
        self.assertEqual(
            caught.exception.lines,
            ["architect: no such role definition; known: coder, coder-hard, manager, product-manager"],
        )
        with self.assertRaises(SetupError) as caught:
            self.one("coder", "acme")
        self.assertEqual(caught.exception.lines, ["acme: no such provider; those with a dictionary: claude-code, codex"])


class HighStakesTests(FixtureCase):
    def test_it_raises_the_product_manager_to_the_frontier_model(self) -> None:
        self.write(self.project_file, "[roles]\nhigh_stakes = true\n")
        expected = dict(DEFAULTS)
        expected["product-manager", "claude-code"] = ("fable", "high")
        expected["product-manager", "codex"] = ("gpt-6-astra", "high")
        self.assertEqual(self.values(), expected)
        found = self.one("product-manager", "claude-code")
        self.assertEqual(
            (found.tier.value, found.tier.layer, found.tier.key), ("frontier", "role", "profile.high_stakes_tier")
        )
        # The switch is part of what decided the model, so its layer counts.
        self.assertEqual(found.model_layer, "project")
        self.assertEqual(
            found.high_stakes, profiles.Source(True, "project", self.project_file, "roles.high_stakes")
        )

    def test_the_layer_that_decided_is_the_switchs(self) -> None:
        for layer, file in (("user", self.user_file), ("project", self.project_file), ("local", self.local_file)):
            with self.subTest(layer=layer):
                self.write(file, "[roles]\nhigh_stakes = true\n")
                found = self.one("product-manager", "codex")
                self.assertEqual((found.model, found.model_layer), ("gpt-6-astra", layer))
                self.assertEqual((found.high_stakes.layer, found.high_stakes.file), (layer, file))
                self.assertEqual(found.effort_layer, "role")

    def test_a_later_tier_map_is_still_the_later_say(self) -> None:
        self.write(self.user_file, "[roles]\nhigh_stakes = true\n")
        self.write(self.local_file, '[providers.codex.tiers]\nfrontier = "gpt-6-sol"\n')
        found = self.one("product-manager", "codex")
        self.assertEqual((found.model, found.model_layer, found.high_stakes.layer), ("gpt-6-sol", "local", "user"))

    def test_a_role_without_a_high_stakes_tier_is_not_touched(self) -> None:
        self.write(self.project_file, "[roles]\nhigh_stakes = true\n")
        for definition in ("coder", "coder-hard", "manager"):
            with self.subTest(definition=definition):
                found = self.one(definition, "claude-code")
                self.assertIsNone(found.high_stakes)
                self.assertEqual(found.model_layer, "role")

    def test_off_there_is_no_switch_in_the_profile(self) -> None:
        self.assertIsNone(self.one("product-manager", "codex").high_stakes)

    def test_false_in_a_later_layer_turns_it_off(self) -> None:
        self.write(self.user_file, "[roles]\nhigh_stakes = true\n")
        self.write(self.local_file, "[roles]\nhigh_stakes = false\n")
        self.assertEqual(self.values(), DEFAULTS)
        self.assertIsNone(self.one("product-manager", "codex").high_stakes)

    def test_a_tier_override_wins_over_the_high_stakes_tier(self) -> None:
        self.write(self.user_file, '[roles]\nhigh_stakes = true\n[roles.product-manager]\ntier = "standard"\n')
        found = self.one("product-manager", "claude-code")
        self.assertEqual((found.model, found.tier.key, found.model_layer), ("sonnet", "roles.product-manager.tier", "user"))
        self.assertIsNone(found.high_stakes)

    def test_a_tier_override_wins_whichever_layer_sets_each(self) -> None:
        """Documented, and meant: the explicit setting for one role beats
        the general switch, even from an earlier layer."""
        self.write(self.user_file, '[roles.product-manager]\ntier = "standard"\n')
        for later in (self.project_file, self.local_file):
            with self.subTest(switch=later.name):
                self.write(later, "[roles]\nhigh_stakes = true\n")
                found = self.one("product-manager", "codex")
                self.assertEqual((found.model, found.tier.layer, found.model_layer), ("gpt-6.1-sol", "user", "user"))
                self.assertIsNone(found.high_stakes)
        # And the other way about: the switch in the user's file, the tier later.
        self.local_file.unlink()
        self.write(self.user_file, "[roles]\nhigh_stakes = true\n")
        self.write(self.project_file, '[roles.product-manager]\ntier = "fast"\n')
        self.assertEqual(self.one("product-manager", "codex").model, "gpt-6-luna")
        self.assertIn("beats ``roles.high_stakes``", " ".join(profiles.__doc__.split()))

    def test_an_effort_override_leaves_the_high_stakes_tier(self) -> None:
        self.write(self.user_file, '[roles]\nhigh_stakes = true\n[roles.product-manager]\neffort = "max"\n')
        found = self.one("product-manager", "claude-code")
        self.assertEqual((found.model, found.effort, found.high_stakes.layer), ("fable", "max", "user"))

    def test_an_explicit_model_is_not_the_switchs_doing(self) -> None:
        self.write(self.user_file, '[providers.codex.role_models]\nproduct-manager = "gpt-6-sol"\n')
        self.write(self.local_file, "[roles]\nhigh_stakes = true\n")
        found = self.one("product-manager", "codex")
        self.assertEqual((found.model, found.model_layer), ("gpt-6-sol", "user"))
        self.assertEqual(self.one("product-manager", "claude-code").model_layer, "local")


class OverrideTests(FixtureCase):
    def test_a_user_override(self) -> None:
        self.write(self.user_file, '[roles.manager]\ntier = "deep"\n')
        found = self.one("manager", "claude-code")
        self.assertEqual((found.model, found.effort), ("opus", "medium"))
        self.assertEqual((found.model_layer, found.effort_layer), ("user", "role"))
        self.assertEqual((found.tier.layer, found.tier.file, found.tier.key), ("user", self.user_file, "roles.manager.tier"))
        self.assertEqual(found.effort_name.key, "profile.effort")

    def test_a_project_override_wins_over_the_users(self) -> None:
        self.write(self.user_file, '[roles.manager]\ntier = "deep"\neffort = "low"\n')
        self.write(self.project_file, '[roles.manager]\ntier = "frontier"\n')
        found = self.one("manager", "codex")
        self.assertEqual((found.model, found.effort), ("gpt-6-astra", "low"))
        self.assertEqual((found.model_layer, found.effort_layer), ("project", "user"))
        self.assertEqual(found.tier.file, self.project_file)
        self.assertEqual(self.all(project=False)["manager", "codex"].model_layer, "user")

    def test_an_overridden_map_is_the_layer_when_it_is_the_later_one(self) -> None:
        self.write(self.user_file, '[providers.claude-code.tiers]\nstandard = "opus"\n[providers.codex.efforts]\nhigh = "xhigh"\n')
        manager = self.one("manager", "claude-code")
        self.assertEqual((manager.model, manager.model_layer, manager.tier.layer), ("opus", "user", "role"))
        hard = self.one("coder-hard", "codex")
        self.assertEqual((hard.effort, hard.effort_layer, hard.effort_name.layer), ("xhigh", "user", "role"))
        self.write(self.project_file, '[roles.manager]\ntier = "standard"\n')
        self.assertEqual(self.one("manager", "claude-code").model_layer, "project")

    def test_coder_and_coder_hard_are_independent(self) -> None:
        self.write(self.user_file, '[roles.coder]\ntier = "frontier"\neffort = "max"\n')
        self.assertEqual(self.values()["coder", "claude-code"], ("fable", "max"))
        self.assertEqual(self.values()["coder-hard", "claude-code"], DEFAULTS["coder-hard", "claude-code"])
        self.write(self.user_file, '[roles.coder-hard]\ntier = "frontier"\neffort = "max"\n')
        self.assertEqual(self.values()["coder-hard", "codex"], ("gpt-6-astra", "max"))
        self.assertEqual(self.values()["coder", "codex"], DEFAULTS["coder", "codex"])
        self.assertEqual(self.one("coder-hard", "codex").tier.key, "roles.coder-hard.tier")

    def test_a_project_override_of_one_tier_changes_that_role_only(self) -> None:
        """R8.3, as far as the profile goes."""
        self.write(self.user_file, '[roles.coder]\neffort = "high"\n')
        before = self.all()
        self.write(self.project_file, '[roles.product-manager]\ntier = "frontier"\n')
        after = self.all()
        changed = {key for key in before if before[key] != after[key]}
        self.assertEqual(changed, {("product-manager", "claude-code"), ("product-manager", "codex")})
        self.assertEqual(after["product-manager", "claude-code"].model, "fable")
        self.assertEqual(after["product-manager", "codex"].model, "gpt-6-astra")
        self.assertEqual(after, {**before, **{key: after[key] for key in changed}})
        self.assertEqual(self.all(project=False), before)


class RoleModelsTests(FixtureCase):
    def test_an_explicit_model_wins_over_the_tier(self) -> None:
        self.write(self.user_file, '[roles.coder-hard]\ntier = "fast"\n')
        self.write(self.project_file, '[providers.codex.role_models]\ncoder-hard = "gpt-6-astra"\n')
        found = self.one("coder-hard", "codex")
        self.assertEqual((found.model, found.effort), ("gpt-6-astra", "high"))
        self.assertTrue(found.explicit_model)
        self.assertEqual(found.model_layer, "project")
        self.assertEqual(found.model_from.key, "providers.codex.role_models.coder-hard")
        self.assertEqual(found.tier.value, "fast")
        # The other provider, and the other Coder, still go by the tier.
        self.assertEqual(self.one("coder-hard", "claude-code").model, "haiku")
        self.assertEqual(self.values()["coder", "codex"], DEFAULTS["coder", "codex"])

    def test_the_layer_is_the_entrys_even_under_a_later_tier_override(self) -> None:
        self.write(self.user_file, '[providers.claude-code.role_models]\nmanager = "opus"\n')
        self.write(self.project_file, '[roles.manager]\ntier = "frontier"\n')
        found = self.one("manager", "claude-code")
        self.assertEqual((found.model, found.model_layer), ("opus", "user"))

    def test_a_model_the_dictionary_does_not_list_is_not_checked(self) -> None:
        self.write(self.user_file, '[providers.claude-code.role_models]\ncoder = "claude-opus-5-5"\n[roles.coder]\neffort = "max"\n')
        found = self.one("coder", "claude-code")
        self.assertEqual((found.model, found.effort), ("claude-opus-5-5", "max"))
        self.assertEqual(
            found.notes,
            ('the claude-code dictionary does not list the model "claude-opus-5-5", so the effort "max" is not checked',),
        )

    def test_an_unlisted_model_named_by_a_tier_map(self) -> None:
        self.write(self.user_file, '[providers.codex.tiers]\nstandard = "gpt-7"\n')
        found = self.one("manager", "codex")
        self.assertEqual((found.model, found.effort, len(found.notes)), ("gpt-7", "medium", 1))
        self.assertEqual(self.one("coder-hard", "codex").notes, ())


class EffortCheckTests(FixtureCase):
    def test_an_effort_the_model_does_not_accept_is_an_error(self) -> None:
        self.write(self.user_file, '[providers.codex.tiers]\ndeep = "gpt-5.5"\n')
        self.write(self.project_file, '[roles.coder-hard]\neffort = "max"\n')
        coder = self.roles_dir / "coder" / "role.toml"
        self.assertEqual(
            self.error(),
            [
                'role coder-hard, provider codex: the model "gpt-5.5" does not accept the effort "max"; '
                "it accepts: low, medium, high, xhigh. "
                f"The model is from providers.codex.tiers.deep ({self.user_file}); the effort is "
                f'roles.coder-hard.effort = "max" ({self.project_file}), '
                f"mapped by providers.codex.efforts.max ({self.codex_dictionary})"
            ],
        )
        self.project_file.unlink()
        self.assertEqual(self.values()["coder-hard", "codex"], ("gpt-5.5", "high"))
        self.assertEqual(self.one("coder-hard", "codex").tier.file, coder)

    def test_an_effort_map_override_that_a_model_does_not_accept(self) -> None:
        self.write(self.user_file, '[providers.codex.efforts]\nmax = "ultra"\n[roles.coder]\ntier = "fast"\neffort = "max"\n')
        (line,) = self.error()
        self.assertTrue(
            line.startswith(
                'role coder, provider codex: the model "gpt-6-luna" does not accept the effort "ultra"; '
                "it accepts: low, medium, high, xhigh, max."
            ),
            line,
        )

    def test_every_unaccepted_effort_is_reported_at_once(self) -> None:
        self.write(self.user_file, '[providers.codex.tiers]\nstandard = "gpt-5.5"\n[roles.coder]\neffort = "max"\n[roles.manager]\neffort = "max"\n')
        lines = self.error()
        self.assertEqual([line.split(":")[0] for line in lines], ["role coder, provider codex", "role manager, provider codex"])

    def test_a_model_that_takes_no_effort_resolves_with_none(self) -> None:
        self.write(self.user_file, '[roles.coder]\ntier = "fast"\neffort = "max"\n')
        found = self.one("coder", "claude-code")
        self.assertEqual((found.model, found.effort), ("haiku", None))
        self.assertEqual(
            found.notes,
            ('the claude-code dictionary lists the model "haiku" as taking no effort setting, so none is written',),
        )
        self.assertEqual((found.effort_name.value, found.effort_from.value), ("max", "max"))
        self.assertEqual(self.values()["coder", "codex"], ("gpt-6-luna", "max"))

    def test_faults_of_settings_stop_the_resolution(self) -> None:
        self.write(self.user_file, '[roles.coder]\ntier = "huge"\n[providers.codex]\nwhat = 1\n')
        lines = self.error()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith(f"{self.user_file}: roles.coder.tier:"), lines[0])
        self.assertTrue(lines[1].startswith(f"{self.user_file}: providers.codex.what:"), lines[1])


class FakeCloneTests(support.CloneCase):
    """Roles and a dictionary the test writes."""

    def setUp(self) -> None:
        super().setUp()
        self.write(self.dictionary, support.VALID_DICTIONARY)

    def values(self) -> dict:
        return {(item.definition, item.provider): (item.model, item.effort) for item in profiles.resolve_all(self.where())}

    def error(self) -> list[str]:
        with self.assertRaises(SetupError) as caught:
            profiles.resolve_all(self.where())
        return caught.exception.lines

    def test_the_effort_is_the_providers_value_not_the_name(self) -> None:
        self.write_role("scout", 'tier = "fast"\neffort = "low"\n')
        self.write_role("judge", 'tier = "frontier"\neffort = "max"\n')
        self.assertEqual(self.values(), {("judge", "acme"): ("a.large", "extreme"), ("scout", "acme"): ("a-small", "minimal")})

    def test_the_hard_definition_does_not_take_the_high_stakes_tier(self) -> None:
        self.write_role("builder", 'tier = "fast"\neffort = "low"\nhigh_stakes_tier = "frontier"\n\n[profile.hard]\ntier = "standard"\neffort = "medium"\n')
        self.assertEqual(self.values(), {("builder", "acme"): ("a-small", "minimal"), ("builder-hard", "acme"): ("a-mid", "medium")})
        self.write(self.user_file, "[roles]\nhigh_stakes = true\n")
        self.assertEqual(self.values(), {("builder", "acme"): ("a.large", "minimal"), ("builder-hard", "acme"): ("a-mid", "medium")})

    def test_the_cache_is_the_providers_value_and_none_where_it_has_no_such_setting(self) -> None:
        self.write_role("lead", 'tier = "fast"\neffort = "low"\ncache = "long"\n\n[profile.hard]\ntier = "standard"\neffort = "medium"\n')
        self.write_role("scout", 'tier = "fast"\neffort = "low"\n')
        caches = lambda: {item.definition: item.cache for item in profiles.resolve_all(self.where())}
        # The dictionary maps no cache: the key is accepted, nothing comes of it, and nothing is said.
        self.assertEqual(caches(), {"lead": None, "lead-hard": None, "scout": None})
        self.assertEqual([item.notes for item in profiles.resolve_all(self.where())], [(), (), ()])
        self.assertEqual(profiles.resolution(self.where()).notes, ())
        self.write(self.dictionary, support.VALID_DICTIONARY + '\n[cache]\nlong = "an-hour"\n')
        # The hard definition does not take it, and a role that names none has none.
        self.assertEqual(caches(), {"lead": "an-hour", "lead-hard": None, "scout": None})
        self.assertEqual(roles.load_all(self.where())["lead"].definitions[0].cache, "long")

    def test_an_unaccepted_effort_from_the_role_file_names_it(self) -> None:
        file = self.write_role("scout", 'tier = "fast"\neffort = "high"\n')
        self.assertEqual(
            self.error(),
            [
                'role scout, provider acme: the model "a-small" does not accept the effort "high"; '
                "it accepts: minimal, medium. "
                f"The model is from providers.acme.tiers.fast ({self.dictionary}); the effort is "
                f'profile.effort = "high" ({file}), mapped by providers.acme.efforts.high ({self.dictionary})'
            ],
        )

    def test_a_no_effort_model_named_under_role_models(self) -> None:
        self.write_role("scout", 'tier = "fast"\neffort = "high"\n')
        self.write(self.user_file, '[providers.acme.role_models]\nscout = "a-plain"\n')
        (found,) = profiles.resolve_all(self.where())
        self.assertEqual((found.model, found.effort, found.explicit_model, len(found.notes)), ("a-plain", None, True, 1))

    def test_a_provider_without_a_dictionary_is_not_resolved_against(self) -> None:
        self.write_role("scout", 'tier = "fast"\neffort = "low"\n')
        self.write(self.user_file, '[providers.other.tiers]\nfast = "x"\n')
        self.assertEqual(list(self.values()), [("scout", "acme")])

    def test_no_roles_or_no_dictionaries_resolve_to_nothing(self) -> None:
        self.assertEqual(profiles.resolve_all(self.where()), [])
        self.dictionary.unlink()
        self.write_role("scout", 'tier = "fast"\neffort = "low"\n')
        self.assertEqual(profiles.resolve_all(self.where()), [])

    def test_faults_of_roles_settings_and_dictionaries_come_together(self) -> None:
        role = self.write_role("scout", 'tier = "fast"\n')
        self.write(self.user_file, "[roles]\nno_such = 1\n")
        self.write(self.dictionary, "this is [not toml\n")
        lines = self.error()
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(lines[0].startswith(f"{role}: profile.effort: missing"), lines[0])
        self.assertTrue(lines[1].startswith(f"{self.user_file}: roles.no_such: unknown key"), lines[1])
        self.assertTrue(lines[2].startswith(f"{self.dictionary}: is not valid TOML"), lines[2])


class RoleFileTests(support.CloneCase):
    def problems(self) -> list[str]:
        with self.assertRaises(SetupError) as caught:
            roles.load_all(self.where())
        return caught.exception.lines

    def test_the_fixture_roles(self) -> None:
        for role, text in support.FIXTURE_ROLES.items():
            self.write(self.role_file(role), text)
        found = roles.load_all(self.locations())
        self.assertEqual(list(found), ["coder", "manager", "product-manager"])
        self.assertEqual(found["product-manager"].title, "Product Manager")
        self.assertEqual(found["product-manager"].definitions[0].high_stakes_tier, "frontier")
        self.assertEqual([item.id for item in found["coder"].definitions], ["coder", "coder-hard"])
        self.assertIsNone(found["coder"].definitions[1].high_stakes_tier)
        self.assertEqual(found["manager"].data["limits"]["edits"], False)

    def link(self, target, link) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are not permitted here: {exc}")

    def test_a_dangling_link_where_a_role_file_or_a_role_directory_belongs(self) -> None:
        self.write_role("scout", 'tier = "fast"\neffort = "low"\n')
        file = self.role_file("ranger")
        self.link(self.root / "gone.toml", file)
        self.assertEqual(self.problems(), [f"link target missing: {file}"])
        file.unlink()
        file.parent.rmdir()
        self.link(self.root / "gone", file.parent)
        self.assertEqual(self.problems(), [f"link target missing: {file.parent}"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no FIFOs here")
    def test_a_fifo_where_a_role_file_belongs_is_not_opened(self) -> None:
        file = self.role_file("scout")
        file.parent.mkdir(parents=True)
        os.mkfifo(file)
        self.assertEqual(self.problems(), [f"{file}: is not a file"])

    @unittest.skipUnless(support.can_lock_directories(), "permissions do not keep this process out")
    def test_directories_that_cannot_be_read(self) -> None:
        file = self.write_role("scout", 'tier = "fast"\neffort = "low"\n')
        self.write(self.dictionary, support.VALID_DICTIONARY)
        for directory, expected in (
            (self.roles_dir, f"{self.roles_dir}: cannot be read: "),
            (file.parent, f"{file}: cannot be read: "),
        ):
            with self.subTest(directory=directory.name):
                os.chmod(directory, 0)
                try:
                    (line,) = self.problems()
                    with self.assertRaises(SetupError) as caught:
                        profiles.resolve_all(self.where())
                    code, out, err = self.show("roles")
                finally:
                    os.chmod(directory, 0o755)
                self.assertTrue(line.startswith(expected), line)
                self.assertEqual(caught.exception.lines, [line])
                self.assertEqual((code, out, err), (2, "", f"error: {line}\n"))

    def test_a_directory_that_is_not_a_role_is_skipped(self) -> None:
        self.write(self.clone / "roles" / "_shared" / "gates.md", "## Gates\n")
        self.write(self.clone / "roles" / "README.md", "# Roles\n")
        self.write_role("scout", 'tier = "fast"\neffort = "low"\n')
        self.assertEqual(list(roles.load_all(self.where())), ["scout"])

    def test_faults_name_the_file_and_the_key(self) -> None:
        cases = {
            'tier = "huge"\neffort = "low"\n': 'profile.tier: "huge" is not allowed; allowed values: fast, standard, deep, frontier',
            'tier = "fast"\neffort = "xhigh"\n': 'profile.effort: "xhigh" is not allowed; allowed values: low, medium, high, max',
            'tier = "fast"\n': "profile.effort: missing; a profile names a tier and an effort",
            'tier = "fast"\neffort = "low"\nmodel = "x"\n': "profile.model: unknown key; known here: tier, effort, high_stakes_tier, cache, hard",
            'tier = "fast"\neffort = "low"\ncache = "forever"\n': 'profile.cache: "forever" is not allowed; allowed values: long',
            'tier = "fast"\neffort = "low"\ncache = true\n': "profile.cache: expected a string, got a boolean",
            'tier = "fast"\neffort = "low"\n[profile.hard]\ntier = "deep"\neffort = "low"\ncache = "long"\n':
                "profile.hard.cache: unknown key; known here: tier, effort",
            'tier = "fast"\neffort = "low"\nhigh_stakes_tier = 4\n': "profile.high_stakes_tier: expected a string, got an integer",
            'tier = "fast"\neffort = "low"\n[profile.hard]\ntier = "deep"\n': "profile.hard.effort: missing; a profile names a tier and an effort",
            'tier = "fast"\neffort = "low"\n[profile.hard]\ntier = "deep"\neffort = "low"\nhigh_stakes_tier = "frontier"\n':
                "profile.hard.high_stakes_tier: unknown key; known here: tier, effort",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                file = self.write_role("scout", text)
                self.assertEqual(self.problems(), [f"{file}: {expected}"])

    def test_identity_faults(self) -> None:
        file = self.write_role("scout", 'tier = "fast"\neffort = "low"\n', name="ranger")
        self.assertEqual(self.problems(), [f'{file}: name: "ranger" is not the directory\'s name, "scout"'])
        self.write(file, 'name = "scout"\ntitle = 3\n')
        self.assertEqual(
            self.problems(),
            [
                f"{file}: title: expected a string, got an integer",
                f"{file}: description: missing; a role must have it",
                f"{file}: profile: missing; a role must have it",
            ],
        )

    def test_a_directory_without_a_role_file_and_one_that_does_not_parse(self) -> None:
        (self.clone / "roles" / "empty").mkdir(parents=True)
        broken = self.write(self.role_file("broken"), "name = [\n")
        lines = self.problems()
        self.assertTrue(lines[0].startswith(f"{broken}: is not valid TOML"), lines[0])
        self.assertEqual(lines[1], f"{self.role_file('empty')}: missing; a role directory must have it")

    def test_a_directory_name_that_is_not_an_id(self) -> None:
        file = self.write_role("Bad_Name", 'tier = "fast"\neffort = "low"\n')
        (line,) = self.problems()
        self.assertTrue(line.startswith(f'{file}: the directory name "Bad_Name" is not a role id'), line)

    def test_a_hard_definition_that_is_also_a_role(self) -> None:
        file = self.write_role("scout", 'tier = "fast"\neffort = "low"\n[profile.hard]\ntier = "deep"\neffort = "low"\n')
        other = self.write_role("scout-hard", 'tier = "fast"\neffort = "low"\n')
        self.assertEqual(
            self.problems(), [f"{file}: profile.hard: yields the definition scout-hard, which is also the role {other}"]
        )


def _lines(definition: str, provider: str, model: str, effort: str, tier: str, effort_name: str) -> str:
    profile = "profile.hard" if definition.endswith("-hard") else "profile"
    head = f"{definition} @ {provider}"
    return (
        f'{head}: model = "{model}"  (role: {profile}.tier "{tier}" [role], providers.{provider}.tiers.{tier} [shipped])\n'
        f'{head}: effort = "{effort}"  (role: {profile}.effort "{effort_name}" [role], '
        f"providers.{provider}.efforts.{effort_name} [shipped])\n"
    )


SETTINGS_TEXT = (
    "roles.enabled = true  (shipped)\n"
    "roles.manager_default = false  (shipped)\n"
    "roles.high_stakes = false  (shipped)\n"
    "roles.max_parallel_coders = 3  (shipped)\n"
)
TIERS = {"coder": "standard", "coder-hard": "deep", "manager": "standard", "product-manager": "deep"}
PROFILES_TEXT = "\nresolved profiles (definition @ provider):\n" + "".join(
    _lines(definition, provider, model, effort, TIERS[definition], effort)
    for (definition, provider), (model, effort) in DEFAULTS.items()
)


class ShowRolesTests(support.ScratchCase):
    def test_text_is_the_settings_lines_then_the_profiles(self) -> None:
        self.assertEqual(self.show("roles"), (0, SETTINGS_TEXT + PROFILES_TEXT, ""))
        self.assertEqual(self.show("roles", project=False), (0, SETTINGS_TEXT + PROFILES_TEXT, ""))

    def test_only_settings_lines_start_with_the_group(self) -> None:
        self.write(self.user_file, '[roles.coder]\ntier = "deep"\n')
        lines = self.show("roles")[1].splitlines()
        split = lines.index("")
        self.assertTrue(all(line.startswith("roles.") for line in lines[:split]))
        self.assertIn('roles.coder.tier = "deep"  (user)', lines[:split])
        self.assertEqual(lines[split + 1], "resolved profiles (definition @ provider):")
        self.assertEqual(len(lines[split + 2:]), 16)
        self.assertFalse(any(line.startswith("roles.") for line in lines[split + 1:]))

    def test_text_names_the_layer_and_the_keys(self) -> None:
        self.write(self.user_file, '[roles.coder]\ntier = "fast"\n[providers.codex.role_models]\ncoder-hard = "gpt-6-astra"\n')
        self.write(self.project_file, '[roles.manager]\neffort = "max"\n[providers.claude-code.role_models]\nmanager = "claude-opus-5-5"\n')
        out = self.show("roles")[1]
        for line in (
            'coder @ claude-code: model = "haiku"  (user: roles.coder.tier "fast" [user], providers.claude-code.tiers.fast [shipped])',
            'coder @ claude-code: effort = none  (the claude-code dictionary lists the model "haiku" as taking no effort '
            'setting, so none is written; not used: profile.effort "medium" [role], providers.claude-code.efforts.medium [shipped])',
            'coder @ codex: model = "gpt-6-luna"  (user: roles.coder.tier "fast" [user], providers.codex.tiers.fast [shipped])',
            'coder-hard @ codex: model = "gpt-6-astra"  (user: providers.codex.role_models.coder-hard [user])',
            'manager @ claude-code: model = "claude-opus-5-5"  (project: providers.claude-code.role_models.manager [project])',
            'manager @ claude-code: effort = "max"  (project: roles.manager.effort "max" [project], '
            "providers.claude-code.efforts.max [shipped]; the claude-code dictionary does not list the model "
            '"claude-opus-5-5", so the effort "max" is not checked)',
        ):
            with self.subTest(line=line):
                self.assertIn(line + "\n", out)

    def test_high_stakes_in_text(self) -> None:
        self.write(self.local_file, "[roles]\nhigh_stakes = true\n")
        out = self.show("roles")[1]
        self.assertIn("roles.high_stakes = true  (local)\n", out)
        self.assertIn(
            'product-manager @ claude-code: model = "fable"  (local: profile.high_stakes_tier "frontier" [role], '
            "roles.high_stakes [local], providers.claude-code.tiers.frontier [shipped])\n",
            out,
        )
        self.assertEqual(out.count("roles.high_stakes [local]"), 2)
        self.write(self.user_file, '[roles.product-manager]\ntier = "standard"\n')
        out = self.show("roles")[1]
        self.assertNotIn("roles.high_stakes [", out)
        self.assertIn(
            'product-manager @ codex: model = "gpt-6.1-sol"  (user: roles.product-manager.tier "standard" [user], '
            "providers.codex.tiers.standard [shipped])\n",
            out,
        )

    def test_high_stakes_in_json(self) -> None:
        self.write(self.project_file, "[roles]\nhigh_stakes = true\n")
        report = json.loads(self.show("roles", "--json")[1])["profiles"]
        raised = report["product-manager"]
        self.assertEqual(
            raised["high_stakes"],
            {"value": True, "layer": "project", "file": str(self.project_file), "key": "roles.high_stakes"},
        )
        self.assertEqual(raised["tier"]["key"], "profile.high_stakes_tier")
        self.assertEqual(
            {provider: entry["model"]["layer"] for provider, entry in raised["providers"].items()},
            {"claude-code": "project", "codex": "project"},
        )
        for definition in ("coder", "coder-hard", "manager"):
            with self.subTest(definition=definition):
                self.assertIsNone(report[definition]["high_stakes"])
        self.write(self.user_file, '[roles.product-manager]\ntier = "standard"\n')
        report = json.loads(self.show("roles", "--json")[1])["profiles"]
        self.assertIsNone(report["product-manager"]["high_stakes"])
        self.assertEqual(report["product-manager"]["providers"]["codex"]["model"]["layer"], "user")

    def test_an_effort_that_is_not_there_has_no_deciding_layer(self) -> None:
        self.write(self.user_file, '[roles.coder]\ntier = "fast"\neffort = "max"\n')
        found = profiles.resolve(self.locations(), "coder", "claude-code")
        self.assertEqual((found.effort, found.effort_layer), (None, None))
        self.assertEqual(profiles.resolve(self.locations(), "coder", "codex").effort_layer, "user")
        entry = json.loads(self.show("roles", "--json")[1])["profiles"]["coder"]["providers"]
        self.assertEqual(
            entry["claude-code"]["effort"],
            {
                "value": None,
                "layer": None,
                "mapping": None,
                "not_used": {
                    "value": "max",
                    "layer": "shipped",
                    "file": str(self.claude_code_dictionary),
                    "key": "providers.claude-code.efforts.max",
                },
            },
        )
        self.assertEqual(entry["codex"]["effort"]["value"], "max")
        self.assertEqual(entry["codex"]["effort"]["layer"], "user")
        self.assertIsNone(entry["codex"]["effort"]["not_used"])
        self.assertEqual(entry["codex"]["effort"]["mapping"]["key"], "providers.codex.efforts.max")

    def test_json_has_profiles_beside_settings(self) -> None:
        self.write(self.project_file, '[roles.coder]\ntier = "fast"\n[providers.codex.role_models]\ncoder = "gpt-6-sol"\n')
        code, out, err = self.show("roles", "--json")
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(list(report), ["schema_version", "settings", "profiles", "notes"])
        self.assertEqual(report["notes"], [])
        self.assertEqual(
            list(report["settings"]),
            ["roles.enabled", "roles.manager_default", "roles.high_stakes", "roles.max_parallel_coders",
             "roles.coder.tier"],
        )
        self.assertEqual(list(report["profiles"]), DEFINITIONS)
        coder = report["profiles"]["coder"]
        role_file = str(self.roles_dir / "coder" / "role.toml")
        self.assertEqual(
            coder,
            {
                "role": "coder",
                "tier": {"value": "fast", "layer": "project", "file": str(self.project_file), "key": "roles.coder.tier"},
                "effort": {"value": "medium", "layer": "role", "file": role_file, "key": "profile.effort"},
                "high_stakes": None,
                "providers": {
                    "claude-code": {
                        "model": {
                            "value": "haiku",
                            "layer": "project",
                            "from": "tier",
                            "mapping": {
                                "value": "haiku",
                                "layer": "shipped",
                                "file": str(self.claude_code_dictionary),
                                "key": "providers.claude-code.tiers.fast",
                            },
                        },
                        "effort": {
                            "value": None,
                            "layer": None,
                            "mapping": None,
                            "not_used": {
                                "value": "medium",
                                "layer": "shipped",
                                "file": str(self.claude_code_dictionary),
                                "key": "providers.claude-code.efforts.medium",
                            },
                        },
                        "notes": [
                            'the claude-code dictionary lists the model "haiku" as taking no effort setting, '
                            "so none is written"
                        ],
                    },
                    "codex": {
                        "model": {
                            "value": "gpt-6-sol",
                            "layer": "project",
                            "from": "role_models",
                            "mapping": {
                                "value": "gpt-6-sol",
                                "layer": "project",
                                "file": str(self.project_file),
                                "key": "providers.codex.role_models.coder",
                            },
                        },
                        "effort": {
                            "value": "medium",
                            "layer": "role",
                            "mapping": {
                                "value": "medium",
                                "layer": "shipped",
                                "file": str(self.codex_dictionary),
                                "key": "providers.codex.efforts.medium",
                            },
                            "not_used": None,
                        },
                        "notes": [],
                    },
                },
            },
        )
        hard = report["profiles"]["coder-hard"]
        self.assertEqual((hard["role"], hard["tier"]["key"]), ("coder", "profile.hard.tier"))
        self.assertEqual(
            {
                (definition, provider): (entry["model"]["value"], entry["effort"]["value"])
                for definition, found in report["profiles"].items()
                if definition != "coder"
                for provider, entry in found["providers"].items()
            },
            {key: value for key, value in DEFAULTS.items() if key[0] != "coder"},
        )

    def test_every_other_key_prints_as_before(self) -> None:
        self.write(self.user_file, '[roles.coder]\ntier = "deep"\n')
        self.assertEqual(self.show("roles.max_parallel_coders"), (0, "roles.max_parallel_coders = 3  (shipped)\n", ""))
        self.assertEqual(self.show("roles.coder"), (0, 'roles.coder.tier = "deep"  (user)\n', ""))
        self.assertNotIn("resolved profiles", self.show()[1])
        self.assertNotIn("@", self.show()[1])
        for argv in ((), ("roles.coder",), ("providers",), ("process",)):
            with self.subTest(argv=argv):
                self.assertEqual(list(json.loads(self.show(*argv, "--json")[1])), ["schema_version", "settings"])

    def test_an_unaccepted_effort_is_an_error_of_the_command(self) -> None:
        self.write(self.user_file, '[providers.codex.tiers]\nstandard = "gpt-5.5"\n[roles.manager]\neffort = "max"\n')
        code, out, err = self.show("roles")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(
            err.startswith('error: role manager, provider codex: the model "gpt-5.5" does not accept the effort "max"; '),
            err,
        )
        self.assertEqual(err.count("\n"), 1)
        self.assertEqual(self.show("roles", "--json")[:2], (2, ""))
        # The roles group itself is sound, so a key inside it still prints.
        self.assertEqual(self.show("roles.manager.effort"), (0, 'roles.manager.effort = "max"  (user)\n', ""))

    def test_other_lookups_open_neither_role_files_nor_dictionaries(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "notes"\n')
        for argv in (("process",), ("memory",), ("roles.max_parallel_coders",), ("roles.coder",)):
            with self.subTest(argv=argv):
                with mock.patch.object(tomlio, "load", wraps=tomlio.load) as load:
                    self.assertEqual(self.show(*argv)[0], 0)
                self.assertEqual({call.args[0] for call in load.call_args_list}, {self.defaults_file, self.user_file})
        with mock.patch.object(tomlio, "load", wraps=tomlio.load) as load:
            self.show("roles")
        opened = {call.args[0] for call in load.call_args_list}
        self.assertIn(self.roles_dir / "coder" / "role.toml", opened)
        self.assertIn(self.codex_dictionary, opened)


class UnmatchedTests(support.ScratchCase):
    """Overrides that match nothing are said, as notes, and fail nothing."""

    KNOWN = "definitions: coder, coder-hard, manager, product-manager"

    def notes(self) -> list[str]:
        return list(profiles.resolution(self.locations()).notes)

    def test_nothing_unmatched_is_no_note(self) -> None:
        self.write(self.user_file, '[roles.coder-hard]\ntier = "frontier"\n[providers.codex.role_models]\nmanager = "gpt-6-sol"\n')
        self.assertEqual(self.notes(), [])
        self.assertEqual(self.show("roles")[2], "")

    def test_a_roles_table_for_an_id_no_definition_has(self) -> None:
        self.write(self.user_file, '[roles.architect]\ntier = "deep"\neffort = "high"\n[roles.coder]\neffort = "high"\n')
        self.assertEqual(
            self.notes(),
            [
                f"{self.user_file}: roles.architect: no role definition has the id architect, "
                f"so this override changes nothing; {self.KNOWN}"
            ],
        )

    def test_each_file_that_sets_it_is_named(self) -> None:
        self.write(self.user_file, '[roles.architect]\ntier = "deep"\n')
        self.write(self.project_file, '[roles.architect]\neffort = "high"\n[roles.manager-hard]\ntier = "deep"\n')
        notes = self.notes()
        self.assertEqual(len(notes), 3)
        self.assertTrue(notes[0].startswith(f"{self.user_file}: roles.architect: "), notes[0])
        self.assertTrue(notes[1].startswith(f"{self.project_file}: roles.architect: "), notes[1])
        self.assertTrue(notes[2].startswith(f"{self.project_file}: roles.manager-hard: "), notes[2])

    def test_a_role_models_key_for_an_id_no_definition_has(self) -> None:
        self.write(self.project_file, '[providers.codex.role_models]\narchitect = "gpt-6-astra"\ncoder = "gpt-6-sol"\n')
        self.assertEqual(
            self.notes(),
            [
                f"{self.project_file}: providers.codex.role_models.architect: no role definition has the id "
                f"architect, so this model is given to nothing; {self.KNOWN}"
            ],
        )

    def test_a_section_for_a_provider_without_a_dictionary(self) -> None:
        self.write(
            self.user_file,
            '[providers.gemini.tiers]\nfast = "g-1"\ndeep = "g-2"\n[providers.gemini.role_models]\narchitect = "g-3"\n',
        )
        self.assertEqual(
            self.notes(),
            [
                f"{self.user_file}: providers.gemini: no provider of this name has a dictionary, "
                "so this section is not used; providers: claude-code, codex"
            ],
        )

    def test_the_resolver_returns_them_beside_the_profiles(self) -> None:
        self.write(self.user_file, '[roles.architect]\ntier = "deep"\n')
        found = profiles.resolution(self.locations())
        self.assertEqual(list(found.profiles), profiles.resolve_all(self.locations()))
        self.assertEqual(len(found.profiles), len(DEFAULTS))
        self.assertEqual(len(found.notes), 1)
        self.assertEqual(
            profiles.unmatched(["coder"], ["codex"], {}), []
        )

    def test_show_roles_prints_them_to_stderr_and_exits_with_zero(self) -> None:
        self.write(self.user_file, '[roles.architect]\ntier = "deep"\n[providers.gemini.tiers]\nfast = "g-1"\n')
        before = self.show("roles", project=False)
        self.user_file.unlink()
        clean = self.show("roles", project=False)
        self.write(self.user_file, '[roles.architect]\ntier = "deep"\n[providers.gemini.tiers]\nfast = "g-1"\n')
        code, out, err = before
        self.assertEqual(code, 0)
        self.assertEqual(
            err,
            f"note: {self.user_file}: roles.architect: no role definition has the id architect, "
            f"so this override changes nothing; {self.KNOWN}\n"
            f"note: {self.user_file}: providers.gemini: no provider of this name has a dictionary, "
            "so this section is not used; providers: claude-code, codex\n",
        )
        # Stdout is the settings line that was set, and the same profiles.
        self.assertEqual(out, clean[1].replace("\n\nresolved", '\nroles.architect.tier = "deep"  (user)\n\nresolved'))

    def test_show_roles_json_carries_them_and_keeps_stderr_empty(self) -> None:
        self.write(self.project_file, '[roles.architect]\ntier = "deep"\n')
        code, out, err = self.show("roles", "--json")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["notes"], self.notes())
        self.assertEqual(len(self.notes()), 1)

    def test_other_keys_say_nothing(self) -> None:
        self.write(self.user_file, '[roles.architect]\ntier = "deep"\n[providers.gemini.tiers]\nfast = "g-1"\n')
        for argv in ((), ("roles.architect",), ("providers",), ("process",)):
            with self.subTest(argv=argv):
                self.assertEqual(self.show(*argv)[2], "")
                self.assertNotIn("notes", json.loads(self.show(*argv, "--json")[1]))


class RepositoryTests(support.ScratchCase):
    """The repository's own roles on its own dictionaries. Subset checks
    only: a role added to roles/, or a dictionary brought up to a newer
    provider version, edits nothing here."""

    EXISTING = {"coder": "coder", "coder-hard": "coder", "manager": "manager", "product-manager": "product-manager"}

    def test_the_roles_load(self) -> None:
        found = roles.load_all(self.repository())
        self.assertLessEqual(set(self.EXISTING.values()), set(found))
        ids = [item.id for item in roles.definitions(self.repository())]
        self.assertLessEqual(set(self.EXISTING), set(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([item.id for item in found["coder"].definitions], ["coder", "coder-hard"])
        self.assertIsNotNone(found["product-manager"].definitions[0].high_stakes_tier)
        for name, role in found.items():
            with self.subTest(role=name):
                self.assertEqual(role.file, support.REPOSITORY / "roles" / name / "role.toml")

    def test_every_definition_resolves_on_every_provider(self) -> None:
        found = profiles.resolution(self.repository())
        self.assertEqual(found.notes, ())
        by_key = {(item.definition, item.provider): item for item in found.profiles}
        providers = {item.provider for item in found.profiles}
        self.assertLessEqual({"claude-code", "codex"}, providers)
        for definition, role in self.EXISTING.items():
            for provider in ("claude-code", "codex"):
                with self.subTest(definition=definition, provider=provider):
                    item = by_key[definition, provider]
                    self.assertEqual(item.role, role)
                    self.assertTrue(item.model)
                    self.assertEqual((item.tier.layer, item.model_layer), ("role", "role"))
                    self.assertFalse(item.explicit_model)
        self.assertEqual(len(found.profiles), len({item.definition for item in found.profiles}) * len(providers))

    def test_show_roles_runs_on_the_repository(self) -> None:
        code, out, err = self.show_repository("roles")
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        split = lines.index("")
        self.assertTrue(all(line.startswith("roles.") for line in lines[:split]))
        profile_lines = lines[split + 2:]
        self.assertEqual(len(profile_lines) % 2, 0)
        for definition in self.EXISTING:
            for provider in ("claude-code", "codex"):
                with self.subTest(definition=definition, provider=provider):
                    self.assertTrue(any(line.startswith(f"{definition} @ {provider}: model = ") for line in profile_lines))
        report = json.loads(self.show_repository("roles", "--json")[1])
        self.assertLessEqual(set(self.EXISTING), set(report["profiles"]))
        self.assertEqual(report["notes"], [])


if __name__ == "__main__":
    unittest.main()
