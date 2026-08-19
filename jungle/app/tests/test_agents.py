"""Agent configuration sync (spec 008).

The database is faked, as everywhere else in this suite. What these pin is the part
that would be expensive to get wrong rather than merely annoying:

  * **redaction**, because the failure mode is publishing an API key on a page that
    is reachable from the internet;
  * **path and archive validation**, because both inputs are attacker-controlled;
  * **change detection**, because it runs on the digest of what arrived and not on
    the redacted text that was kept, and those two are deliberately different.
"""

import hashlib
import io
import zipfile
from datetime import UTC, datetime

import pytest

from brownbear import agents as agents_service
from brownbear.agents import Branch, ConfigRejected, ZipLimits, ZipRejected
from brownbear.models.agents import ConfigContentKind, ConfigStatus

BRANCH = Branch(
    machine="laptop", scope_kind="project", project="brownbear", tool="claude"
)


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestAddress:
    def test_machine_keeps_dots_and_dashes(self):
        """A hostname is a label here, not a matching key: collapsing it the way
        project names are collapsed would leave the tree unreadable."""
        assert (
            agents_service.normalise_machine("Mahabubs-MacBook.local")
            == "mahabubs-macbook.local"
        )

    def test_machine_strips_everything_else(self):
        assert agents_service.normalise_machine("Bob's Box!") == "bob-s-box"

    def test_machine_never_empty(self):
        assert agents_service.normalise_machine("  ") == "unknown"
        assert agents_service.normalise_machine("!!!") == "unknown"

    def test_tool_is_allowlisted(self):
        assert agents_service.normalise_tool("Claude") == "claude"
        assert agents_service.normalise_tool("QWEN") == "qwen"

    def test_unknown_tool_names_the_accepted_values(self):
        with pytest.raises(ConfigRejected) as raised:
            agents_service.normalise_tool("cursor")
        assert "claude" in raised.value.reason and "qwen" in raised.value.reason

    def test_global_scope_has_no_project(self):
        assert agents_service.normalise_scope("global", "anything") == ("global", "")

    def test_project_scope_uses_the_gateway_rule(self):
        """Same normalisation as exchanges and chunks, so a branch scopes exactly
        as everything else already does."""
        assert agents_service.normalise_scope("project", "Brown-Bear") == ("project", "brownbear")

    def test_project_scope_needs_a_project(self):
        with pytest.raises(ConfigRejected):
            agents_service.normalise_scope("project", "   ")

    def test_unknown_scope_is_rejected(self):
        with pytest.raises(ConfigRejected):
            agents_service.normalise_scope("team", "x")

    def test_id_is_derived_from_the_whole_address(self):
        one = agents_service.config_id("a", "project", "p", "claude", "settings.json")
        two = agents_service.config_id("a", "project", "p", "qwen", "settings.json")
        assert one != two
        assert one.startswith("a_") and len(one) == 34

    def test_id_is_stable(self):
        args = ("a", "global", "", "claude", "skills/run/SKILL.md")
        assert agents_service.config_id(*args) == agents_service.config_id(*args)

    def test_path_components_cannot_be_shuffled_into_the_same_id(self):
        """NUL-joined, so `a/b` + `c` cannot hash the same as `a` + `b/c`."""
        one = agents_service.config_id("a", "project", "b", "claude", "c")
        two = agents_service.config_id("a", "project", "b", "claude/c", "")
        assert one != two


class TestPathSafety:
    def test_accepts_a_nested_relative_path(self):
        assert agents_service.normalise_path("skills/run/SKILL.md") == "skills/run/SKILL.md"

    def test_drops_redundant_segments(self):
        assert agents_service.normalise_path("./agents//plan.md") == "agents/plan.md"

    @pytest.mark.parametrize(
        "path",
        [
            "../../etc/passwd",
            "skills/../../secret",
            "/etc/passwd",
            "C:/Windows/system.ini",
            "skills\\run\\SKILL.md",
            "bad\x00name",
            "",
            "   ",
            "./",
        ],
    )
    def test_rejects_rather_than_repairs(self, path):
        """A path that has to be rewritten to be safe is a path whose meaning is
        already unclear — storing `etc/passwd` for a client that sent
        `../../etc/passwd` would invent a file nobody has."""
        with pytest.raises(ConfigRejected):
            agents_service.normalise_path(path)

    def test_rejects_an_overlong_path(self):
        with pytest.raises(ConfigRejected):
            agents_service.normalise_path("a/" * 300 + "b")


class TestDeniedPaths:
    @pytest.mark.parametrize(
        "path",
        [
            ".credentials.json",
            "nested/.credentials.json",
            ".env",
            ".env.local",
            "certs/client.pem",
            "keys/deploy.key",
            ".netrc",
        ],
    )
    def test_credential_files_are_refused_outright(self, path):
        """Masking one leaves nothing to read, so it is refused with the reason —
        a silent skip reads as 'synced' to whoever is looking at the tree."""
        assert agents_service.denial_reason(path) is not None

    @pytest.mark.parametrize("path", ["settings.json", "CLAUDE.md", "hooks/pre.sh", "env.md"])
    def test_ordinary_files_are_allowed(self, path):
        assert agents_service.denial_reason(path) is None


class TestRedaction:
    def test_masks_an_env_block_wholesale(self):
        """Claude Code puts environment variables in `env`, and an environment
        variable is a credential often enough that name-matching each one is the
        wrong bet."""
        text = '{"env": {"ANTHROPIC_API_KEY": "sk-ant-abc123456789012", "DEBUG": "1"}}'
        out, count = agents_service.redact(text)
        assert "sk-ant-abc123456789012" not in out
        assert '"DEBUG": "«redacted»"' in out
        assert count == 2

    def test_masks_a_keyed_json_value(self):
        out, count = agents_service.redact('{"authToken": "hunter2hunter2"}')
        assert "hunter2hunter2" not in out
        assert '"authToken": "«redacted»"' in out
        assert count == 1

    def test_masks_a_shell_assignment_without_putting_it_back(self):
        """The bug this guards: a two-group pattern reads identically whether the
        second group is a closing quote to keep or the secret itself."""
        out, count = agents_service.redact(
            "GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaa\nHOME=/root"
        )
        assert "ghp_aaaaaaaaaaaaaaaaaaaaaa" not in out
        assert "GITHUB_TOKEN=«redacted»" in out
        assert "HOME=/root" in out
        assert count == 1

    @pytest.mark.parametrize(
        "secret",
        [
            "sk-ant-api03-aaaaaaaaaaaaaaaaaaaa",
            "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "ghp_aaaaaaaaaaaaaaaaaaaaaaaa",
            "AKIAIOSFODNN7EXAMPLE",
            "xoxb-1234567890-abcdefghij",
        ],
    )
    def test_masks_provider_shaped_literals_anywhere(self, secret):
        """Including in prose: a README that pastes a real key is exactly as
        published as a settings file that holds one."""
        out, count = agents_service.redact(f"# notes\nuse {secret} when testing\n")
        assert secret not in out
        assert count == 1

    def test_masks_a_private_key_block_but_keeps_its_fences(self):
        text = (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nnope\n"
            "-----END RSA PRIVATE KEY-----\n"
        )
        out, count = agents_service.redact(text)
        assert "MIIEowIBAAKCAQEA" not in out
        assert out.startswith("-----BEGIN RSA PRIVATE KEY-----")
        assert "-----END RSA PRIVATE KEY-----" in out
        assert count == 1

    def test_masks_a_bearer_header(self):
        out, count = agents_service.redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012")
        assert "abcdefghijklmnopqrstuvwxyz012" not in out
        assert count == 1

    def test_leaves_an_ordinary_file_alone(self):
        text = '{"model": "claude-opus-5", "permissions": {"allow": ["Bash(ls:*)"]}}'
        out, count = agents_service.redact(text)
        assert out == text
        assert count == 0

    def test_is_idempotent_and_does_not_double_count(self):
        once, first = agents_service.redact('{"apiKey": "abcdefghijkl"}')
        twice, second = agents_service.redact(once)
        assert twice == once
        assert first == 1 and second == 0

    def test_works_on_malformed_json(self):
        """json.loads would refuse this and leave the key stored verbatim — and a
        hand-edited, slightly broken settings file is where a key most often is."""
        out, count = agents_service.redact('{"apiKey": "abcdefghijkl",,}')
        assert "abcdefghijkl" not in out
        assert count == 1


class TestDecoding:
    def test_text_round_trips(self):
        text, kind = agents_service.decode(b"# hello", max_bytes=100)
        assert (text, kind) == ("# hello", ConfigContentKind.text)

    def test_binary_has_no_content(self):
        text, kind = agents_service.decode(b"\xff\xfe\x00\x01", max_bytes=100)
        assert text is None
        assert kind is ConfigContentKind.binary

    def test_oversize_is_recorded_never_truncated(self):
        """A configuration file cut off at the cap is a configuration that exists on
        no machine."""
        text, kind = agents_service.decode(b"x" * 200, max_bytes=100)
        assert text is None
        assert kind is ConfigContentKind.too_large


def zip_of(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


LIMITS = ZipLimits(
    max_entries=10, max_total_bytes=4096, max_entry_bytes=1024, max_ratio=200
)


class TestArchives:
    def test_reads_entries(self):
        files = agents_service.unpack_zip(
            zip_of({"settings.json": b"{}", "skills/a/SKILL.md": b"# a"}), LIMITS
        )
        assert dict(files) == {"settings.json": b"{}", "skills/a/SKILL.md": b"# a"}

    def test_skips_directory_entries(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("skills/", b"")
            archive.writestr("skills/a.md", b"x")
        files = agents_service.unpack_zip(buffer.getvalue(), LIMITS)
        assert [name for name, _ in files] == ["skills/a.md"]

    def test_a_traversing_entry_name_survives_unpacking_and_dies_in_prepare(self):
        """Nothing is extracted to disk, so the name cannot escape anything here —
        but it would become a stored path, so it goes through the same validation."""
        files = agents_service.unpack_zip(zip_of({"../../etc/passwd": b"root:x"}), LIMITS)
        assert files == [("../../etc/passwd", b"root:x")]
        with pytest.raises(ConfigRejected):
            agents_service.prepare(BRANCH, files[0][0], files[0][1])

    def test_refuses_too_many_entries(self):
        with pytest.raises(ZipRejected) as raised:
            agents_service.unpack_zip(zip_of({f"f{i}.md": b"x" for i in range(11)}), LIMITS)
        assert "10" in str(raised.value)

    def test_refuses_an_archive_that_expands_past_the_ceiling(self):
        with pytest.raises(ZipRejected):
            agents_service.unpack_zip(zip_of({"big.md": b"x" * 5000}), LIMITS)

    def test_refuses_an_implausible_ratio_before_expanding(self):
        """A 2 MB zip claiming to expand to 4 GB is a bomb, and the claim alone is
        enough to refuse it."""
        bomb = zip_of({"bomb.txt": b"\0" * 500_000})
        limits = ZipLimits(
            max_entries=10,
            max_total_bytes=10_000_000,
            max_entry_bytes=1_000_000,
            max_ratio=5,
        )
        with pytest.raises(ZipRejected) as raised:
            agents_service.unpack_zip(bomb, limits)
        assert "ratio" in str(raised.value)

    def test_a_corrupt_archive_is_refused(self):
        with pytest.raises(ZipRejected):
            agents_service.unpack_zip(b"not a zip at all", LIMITS)


class TestPrepare:
    def test_digests_what_arrived_not_what_is_kept(self):
        """Change detection has to work on the machine's real bytes even though the
        redacted text is what is stored — otherwise two files differing only in
        their secret look identical and the newer one never lands."""
        raw = b'{"apiKey": "abcdefghijkl"}'
        values = agents_service.prepare(BRANCH, "settings.json", raw)
        assert values["sha256"] == digest_of(raw)
        assert values["redactions"] == 1
        assert "abcdefghijkl" not in values["content"]
        assert values["size_bytes"] == len(raw)

    def test_refuses_a_denied_path(self):
        with pytest.raises(ConfigRejected):
            agents_service.prepare(BRANCH, ".credentials.json", b"{}")

    def test_counts_masks_the_client_already_applied(self):
        """The count is of the stored text, not of this server's own pass. A client
        that masked first would otherwise land a file full of «redacted» reporting
        that nothing was hidden — precisely backwards."""
        already = '{"key": "«redacted»"}'.encode()
        values = agents_service.prepare(BRANCH, "settings.json", already)
        assert values["redactions"] == 1

    def test_a_binary_file_has_no_content(self):
        values = agents_service.prepare(BRANCH, "logo.png", b"\x89PNG\r\n\x1a\n\xff\xfe")
        assert values["content"] is None
        assert values["content_kind"] is ConfigContentKind.binary

    def test_an_oversized_file_keeps_its_size_and_digest(self, monkeypatch):
        """Recorded, not truncated: the reader learns the file exists and is 300 KB,
        which is the useful half."""
        from brownbear.config import get_settings

        monkeypatch.setattr(get_settings(), "max_config_file_bytes", 1024, raising=False)
        payload = b"x" * 3000
        values = agents_service.prepare(BRANCH, "big.md", payload)
        assert values["content"] is None
        assert values["content_kind"] is ConfigContentKind.too_large
        assert values["size_bytes"] == 3000
        assert values["sha256"] == digest_of(payload)


class FakeRow:
    """Enough of AgentConfig for the sync path, which only reads a few fields."""

    def __init__(self, **values):
        self.__dict__.update(values)


@pytest.fixture
def rows(monkeypatch):
    """An in-memory stand-in for the branch transaction, with the same semantics."""
    store: dict[str, FakeRow] = {}

    def _sync(branch, incoming, *, prune, now):
        outcomes = []
        seen = set()
        for values in incoming:
            seen.add(values["id"])
            row = store.get(values["id"])
            if row is None:
                store[values["id"]] = FakeRow(
                    id=values["id"],
                    path=values["path"],
                    sha256=values["sha256"],
                    revision=1,
                    redactions=values["redactions"],
                    content_kind=values["content_kind"],
                    status=ConfigStatus.synced,
                )
                outcome, revision = "stored", 1
            else:
                was_removed = row.status == ConfigStatus.removed
                changed = row.sha256 != values["sha256"]
                row.status = ConfigStatus.synced
                if changed:
                    row.revision += 1
                    row.sha256 = values["sha256"]
                outcome = "unchanged" if not changed and not was_removed else "updated"
                revision = row.revision
            outcomes.append(
                {
                    "path": values["path"],
                    "config_id": values["id"],
                    "outcome": outcome,
                    "revision": revision,
                    "redactions": values["redactions"],
                    "content_kind": str(values["content_kind"]),
                }
            )

        removed = 0
        if prune:
            for row in store.values():
                if row.id in seen or row.status == ConfigStatus.removed:
                    continue
                row.status = ConfigStatus.removed
                removed += 1
                outcomes.append(
                    {
                        "path": row.path,
                        "config_id": row.id,
                        "outcome": "removed",
                        "revision": row.revision,
                        "redactions": row.redactions,
                        "content_kind": str(row.content_kind),
                    }
                )
        return outcomes, removed

    monkeypatch.setattr(agents_service, "_sync_sync", _sync)
    return store


class TestSync:
    async def test_stores_then_reports_unchanged(self, rows):
        files = [("settings.json", b"{}"), ("CLAUDE.md", b"# rules")]
        first = await agents_service.sync(BRANCH, files, prune=False)
        assert (first["stored"], first["updated"], first["unchanged"]) == (2, 0, 0)

        second = await agents_service.sync(BRANCH, files, prune=False)
        assert (second["stored"], second["updated"], second["unchanged"]) == (0, 0, 2)
        assert all(row.revision == 1 for row in rows.values())

    async def test_an_edit_bumps_exactly_one_revision(self, rows):
        await agents_service.sync(
            BRANCH, [("settings.json", b"{}"), ("CLAUDE.md", b"# a")], prune=False
        )
        result = await agents_service.sync(
            BRANCH, [("settings.json", b'{"model":"x"}'), ("CLAUDE.md", b"# a")], prune=False
        )
        assert (result["updated"], result["unchanged"]) == (1, 1)
        revisions = sorted(row.revision for row in rows.values())
        assert revisions == [1, 2]

    async def test_a_secret_only_change_still_lands(self, rows):
        """Both versions store as `«redacted»`; the digest of what arrived is what
        makes the second one detectable at all."""
        await agents_service.sync(BRANCH, [("s.json", b'{"apiKey": "aaaaaaaaaaaa"}')], prune=False)
        result = await agents_service.sync(
            BRANCH, [("s.json", b'{"apiKey": "bbbbbbbbbbbb"}')], prune=False
        )
        assert result["updated"] == 1

    async def test_prune_marks_an_absent_path_removed(self, rows):
        await agents_service.sync(BRANCH, [("a.md", b"a"), ("b.md", b"b")], prune=False)
        result = await agents_service.sync(BRANCH, [("a.md", b"a")], prune=True)
        assert result["removed"] == 1
        assert [row.status for row in rows.values() if row.path == "b.md"] == [ConfigStatus.removed]

    async def test_without_prune_a_partial_push_touches_nothing_else(self, rows):
        await agents_service.sync(BRANCH, [("a.md", b"a"), ("b.md", b"b")], prune=False)
        result = await agents_service.sync(BRANCH, [("a.md", b"a")], prune=False)
        assert result["removed"] == 0
        assert all(row.status == ConfigStatus.synced for row in rows.values())

    async def test_a_returning_file_is_resurrected(self, rows):
        await agents_service.sync(BRANCH, [("a.md", b"a"), ("b.md", b"b")], prune=False)
        await agents_service.sync(BRANCH, [("a.md", b"a")], prune=True)
        result = await agents_service.sync(BRANCH, [("a.md", b"a"), ("b.md", b"b")], prune=False)
        # Same bytes as before, but it was removed — so this is a change of state
        # and must not be reported as `unchanged`.
        assert result["updated"] == 1

    async def test_one_bad_path_does_not_cost_the_rest(self, rows):
        result = await agents_service.sync(
            BRANCH,
            [("a.md", b"a"), ("../escape", b"x"), (".credentials.json", b"{}"), ("b.md", b"b")],
            prune=False,
        )
        assert result["stored"] == 2
        assert result["skipped"] == 2
        reasons = [f["reason"] for f in result["files"] if f["outcome"] == "skipped"]
        assert any("escapes" in r for r in reasons)
        assert any("credential" in r for r in reasons)

    async def test_duplicate_paths_are_reported_not_silently_merged(self, rows):
        result = await agents_service.sync(
            BRANCH, [("a.md", b"one"), ("./a.md", b"two")], prune=False
        )
        assert result["stored"] == 1
        assert result["skipped"] == 1

    async def test_respects_the_file_count_cap(self, rows, monkeypatch):
        from brownbear.config import get_settings

        monkeypatch.setattr(get_settings(), "max_sync_files", 2, raising=False)
        result = await agents_service.sync(
            BRANCH, [(f"f{i}.md", b"x") for i in range(5)], prune=False
        )
        assert result["stored"] == 2
        assert result["skipped"] == 3

    async def test_reports_the_branch_it_wrote(self, rows):
        result = await agents_service.sync(BRANCH, [("a.md", b"a")], prune=False)
        assert result["branch"] == "laptop/brownbear/claude"

    async def test_a_global_branch_labels_itself_global(self, rows):
        branch = Branch(machine="laptop", scope_kind="global", project="", tool="qwen")
        result = await agents_service.sync(branch, [("a.md", b"a")], prune=False)
        assert result["branch"] == "laptop/global/qwen"


class TestSyncApi:
    @pytest.fixture(autouse=True)
    def _fake_branch_write(self, rows):
        return rows

    def test_syncs_a_json_snapshot(self, client):
        response = client.post(
            "/ext/agents/sync",
            json={
                "machine": "Mahabubs-MacBook.local",
                "scope": "project",
                "project": "Brown-Bear",
                "tool": "claude",
                "files": [{"path": "settings.json", "content": "{}"}],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["branch"] == "mahabubs-macbook.local/brownbear/claude"
        assert body["stored"] == 1

    def test_reports_what_it_masked(self, client):
        response = client.post(
            "/ext/agents/sync",
            json={
                "machine": "laptop",
                "project": "bb",
                "files": [
                    {
                        "path": "settings.json",
                        "content": '{"env": {"ANTHROPIC_API_KEY": "sk-ant-aaaaaaaaaaaaaa"}}',
                    }
                ],
            },
        )
        body = response.json()
        assert body["redactions"] == 1
        # And the key is nowhere in the response either.
        assert "sk-ant" not in response.text

    def test_rejects_an_unknown_tool(self, client):
        response = client.post(
            "/ext/agents/sync",
            json={"machine": "laptop", "project": "bb", "tool": "cursor", "files": []},
        )
        assert response.status_code == 422
        assert "claude" in response.json()["detail"]

    def test_rejects_a_project_scope_with_no_project(self, client):
        response = client.post("/ext/agents/sync", json={"machine": "laptop", "files": []})
        assert response.status_code == 422

    def test_refuses_a_body_over_the_cap(self, client, monkeypatch):
        from brownbear.config import get_settings

        monkeypatch.setattr(get_settings(), "max_sync_bytes", 64, raising=False)
        response = client.post(
            "/ext/agents/sync",
            json={
                "machine": "laptop",
                "project": "bb",
                "files": [{"path": "a.md", "content": "x" * 500}],
            },
        )
        assert response.status_code == 413

    def test_refuses_a_body_that_does_not_declare_its_length(self, client):
        """A cap that can only be applied after buffering is not a cap."""

        def chunks():
            yield b'{"machine": "laptop", "project": "bb", "files": []}'

        response = client.post("/ext/agents/sync", content=chunks())
        assert response.status_code == 411

    def test_rejects_a_body_that_is_not_json(self, client):
        response = client.post(
            "/ext/agents/sync", content=b"not json", headers={"content-type": "application/json"}
        )
        assert response.status_code == 422

    def test_syncs_an_archive(self, client):
        payload = zip_of({"settings.json": b"{}", "skills/a/SKILL.md": b"# a"})
        response = client.post(
            "/ext/agents/sync/archive",
            files={"archive": ("claude.zip", io.BytesIO(payload), "application/zip")},
            data={"machine": "laptop", "scope": "global", "tool": "qwen"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["branch"] == "laptop/global/qwen"
        assert body["stored"] == 2

    def test_an_archive_entry_that_traverses_is_skipped_not_stored(self, client):
        payload = zip_of({"ok.md": b"x", "../../etc/passwd": b"root:x"})
        response = client.post(
            "/ext/agents/sync/archive",
            files={"archive": ("claude.zip", io.BytesIO(payload), "application/zip")},
            data={"machine": "laptop", "project": "bb"},
        )
        body = response.json()
        assert body["stored"] == 1
        assert body["skipped"] == 1

    def test_an_empty_archive_is_refused(self, client):
        response = client.post(
            "/ext/agents/sync/archive",
            files={"archive": ("claude.zip", io.BytesIO(b""), "application/zip")},
            data={"machine": "laptop", "project": "bb"},
        )
        assert response.status_code == 422

    def test_a_corrupt_archive_is_refused(self, client):
        response = client.post(
            "/ext/agents/sync/archive",
            files={"archive": ("claude.zip", io.BytesIO(b"nonsense"), "application/zip")},
            data={"machine": "laptop", "project": "bb"},
        )
        assert response.status_code == 422


class TestReadApi:
    def test_lists_a_branch_without_content(self, client, monkeypatch):
        row = FakeRow(
            id="a_1",
            machine="laptop",
            scope_kind="project",
            project="brownbear",
            tool="claude",
            path="settings.json",
            sha256="a" * 64,
            size_bytes=12,
            content="{}",
            content_kind=ConfigContentKind.text,
            redactions=2,
            status=ConfigStatus.synced,
            revision=3,
            first_seen_at=None,
            last_synced_at=None,
            changed_at=None,
            removed_at=None,
        )
        monkeypatch.setattr(agents_service, "_list_sync", lambda **kwargs: ([row], 1))

        body = client.get("/ext/agents/files", params={"machine": "Laptop"}).json()
        assert body["total"] == 1
        assert body["files"][0]["path"] == "settings.json"
        assert "content" not in body["files"][0]

    def test_the_listing_normalises_its_filters(self, client, monkeypatch):
        """A caller asking for `Brown-Bear` must not silently get nothing while
        `brownbear` sits in the table."""
        seen: dict[str, object] = {}

        def _list(**kwargs):
            seen.update(kwargs)
            return ([], 0)

        monkeypatch.setattr(agents_service, "_list_sync", _list)
        client.get(
            "/ext/agents/files",
            params={"machine": "Mahabubs-MacBook.local", "project": "Brown-Bear"},
        )
        assert seen["machine"] == "mahabubs-macbook.local"
        assert seen["project"] == "brownbear"

    def test_detail_returns_the_stored_content(self, client, monkeypatch):
        row = FakeRow(
            id="a_1",
            machine="laptop",
            scope_kind="global",
            project="",
            tool="claude",
            path="settings.json",
            sha256="a" * 64,
            size_bytes=12,
            content='{"apiKey": "«redacted»"}',
            content_kind=ConfigContentKind.text,
            redactions=1,
            status=ConfigStatus.synced,
            revision=1,
            first_seen_at=None,
            last_synced_at=None,
            changed_at=None,
            removed_at=None,
        )
        monkeypatch.setattr(agents_service, "_get_sync", lambda i: row)

        body = client.get("/ext/agents/files/a_1").json()
        assert body["content"] == '{"apiKey": "«redacted»"}'
        assert body["label"] == "Global"

    def test_a_missing_file_is_a_404(self, client, monkeypatch):
        monkeypatch.setattr(agents_service, "_get_sync", lambda i: None)
        monkeypatch.setattr(agents_service, "_delete_sync", lambda i: None)
        assert client.get("/ext/agents/files/a_nope").status_code == 404
        assert client.delete("/ext/agents/files/a_nope").status_code == 404

    def test_delete_reports_the_branch_it_purged_from(self, client, monkeypatch):
        row = FakeRow(
            id="a_1", machine="laptop", scope_kind="project", project="brownbear",
            tool="claude", path="settings.json",
        )
        monkeypatch.setattr(agents_service, "_delete_sync", lambda i: row)
        body = client.delete("/ext/agents/files/a_1").json()
        assert body == {
            "config_id": "a_1",
            "path": "settings.json",
            "branch": "laptop/brownbear/claude",
            "deleted": True,
        }

    def test_inventory_nests_machine_scope_tool(self, client, monkeypatch):
        from datetime import UTC, datetime

        stamp = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
        monkeypatch.setattr(
            agents_service,
            "_inventory_sync",
            lambda: [
                {"machine": "laptop", "scope_kind": "global", "project": "", "tool": "claude",
                 "files": 4, "bytes": 400, "redactions": 1, "removed": 0,
                 "last_synced_at": stamp, "changed_at": stamp},
                {"machine": "laptop", "scope_kind": "project", "project": "brownbear",
                 "tool": "claude", "files": 6, "bytes": 600, "redactions": 0, "removed": 1,
                 "last_synced_at": stamp, "changed_at": stamp},
                {"machine": "laptop", "scope_kind": "project", "project": "brownbear",
                 "tool": "qwen", "files": 2, "bytes": 200, "redactions": 0, "removed": 0,
                 "last_synced_at": stamp, "changed_at": stamp},
            ],
        )

        body = client.get("/ext/agents").json()
        assert body["totals"] == {
            "machines": 1,
            "files": 12,
            "bytes": 1200,
            "removed": 1,
            "redactions": 1,
        }
        machine = body["machines"][0]
        assert [s["label"] for s in machine["scopes"]] == ["Global", "brownbear"]
        assert [t["tool"] for t in machine["scopes"][1]["tools"]] == ["claude", "qwen"]
        assert body["stale_after_hours"] > 0

    def test_inventory_is_empty_not_broken_with_no_rows(self, client, monkeypatch):
        monkeypatch.setattr(agents_service, "_inventory_sync", lambda: [])
        body = client.get("/ext/agents").json()
        assert body["machines"] == []
        assert body["totals"]["files"] == 0


class TestPersistence:
    """The few things a faked database cannot check (see the `sqlite_db` fixture)."""

    def test_delete_actually_deletes(self, sqlite_db):
        """The regression this exists for: `session.delete()` then
        `session.expunge()` evicts the instance and discards the pending delete
        with it, so the route reported success and left the row in place."""
        from brownbear.models.agents import AgentConfig, ConfigContentKind

        values = agents_service.prepare(BRANCH, "settings.json", b"{}")
        agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))

        assert agents_service._get_sync(values["id"]) is not None
        removed = agents_service._delete_sync(values["id"])
        assert removed is not None
        assert agents_service._get_sync(values["id"]) is None
        assert ConfigContentKind is not None and AgentConfig is not None

    def test_the_branch_transaction_round_trips(self, sqlite_db):
        now = datetime.now(UTC)
        first = agents_service.prepare(BRANCH, "a.md", b"one")
        second = agents_service.prepare(BRANCH, "b.md", b"two")
        agents_service._sync_sync(BRANCH, [first, second], prune=False, now=now)

        rows, total = agents_service._list_sync(
            machine=BRANCH.machine,
            scope_kind=BRANCH.scope_kind,
            project=BRANCH.project,
            tool=BRANCH.tool,
            status=None,
            limit=10,
            offset=0,
        )
        assert total == 2
        assert sorted(row.path for row in rows) == ["a.md", "b.md"]

    def test_an_edit_moves_changed_at_and_a_resync_does_not(self, sqlite_db):
        from datetime import timedelta

        first_seen = datetime.now(UTC) - timedelta(days=2)
        values = agents_service.prepare(BRANCH, "settings.json", b"{}")
        agents_service._sync_sync(BRANCH, [values], prune=False, now=first_seen)

        # Re-synced unchanged: last_synced_at advances, changed_at must not.
        later = datetime.now(UTC)
        agents_service._sync_sync(BRANCH, [values], prune=False, now=later)
        row = agents_service._get_sync(values["id"])
        assert row is not None
        assert row.changed_at < row.last_synced_at
        unchanged_at = row.changed_at

        edited = agents_service.prepare(BRANCH, "settings.json", b'{"model": "x"}')
        agents_service._sync_sync(BRANCH, [edited], prune=False, now=datetime.now(UTC))
        row = agents_service._get_sync(values["id"])
        assert row is not None
        assert row.changed_at > unchanged_at
        assert row.revision == 2

    def test_prune_marks_in_the_database(self, sqlite_db):
        now = datetime.now(UTC)
        first = agents_service.prepare(BRANCH, "a.md", b"one")
        second = agents_service.prepare(BRANCH, "b.md", b"two")
        agents_service._sync_sync(BRANCH, [first, second], prune=False, now=now)
        _, removed = agents_service._sync_sync(BRANCH, [first], prune=True, now=now)

        assert removed == 1
        gone = agents_service._get_sync(second["id"])
        assert gone is not None and str(gone.status) == "removed"
        # The content survives: a file that disappeared from a machine is
        # information, not an absence.
        assert gone.content == "two"

    def test_the_inventory_rollup_groups_in_sql(self, sqlite_db):
        now = datetime.now(UTC)
        other = Branch(machine="laptop", scope_kind="global", project="", tool="qwen")
        agents_service._sync_sync(
            BRANCH, [agents_service.prepare(BRANCH, "a.md", b"one")], prune=False, now=now
        )
        agents_service._sync_sync(
            other, [agents_service.prepare(other, "b.md", b"two")], prune=False, now=now
        )

        groups = agents_service._inventory_sync()
        assert [(g["scope_kind"], g["tool"], g["files"]) for g in groups] == [
            ("global", "qwen", 1),
            ("project", "claude", 1),
        ]
        assert all(g["removed"] == 0 for g in groups)


class TestRevisionHistory:
    """Spec 010. Exercised against a real database — the whole point of the table is
    what it holds *after* several syncs, which a fake would simply agree with."""

    def test_a_new_file_gets_revision_one(self, sqlite_db):
        values = agents_service.prepare(BRANCH, "settings.json", b"{}")
        agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))

        history = agents_service._revisions_sync(values["id"])
        assert [r.revision for r in history] == [1]
        # replaced_at is null exactly for the current content.
        assert history[0].replaced_at is None

    def test_an_unchanged_resync_writes_no_history(self, sqlite_db):
        """The table grows with edits, not with syncs. A machine syncing every
        session must not accumulate identical revisions."""
        values = agents_service.prepare(BRANCH, "settings.json", b"{}")
        for _ in range(3):
            agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))

        assert len(agents_service._revisions_sync(values["id"])) == 1

    def test_each_edit_is_kept_with_its_content(self, sqlite_db):
        first = agents_service.prepare(BRANCH, "settings.json", b'{"model":"a"}')
        agents_service._sync_sync(BRANCH, [first], prune=False, now=datetime.now(UTC))
        second = agents_service.prepare(BRANCH, "settings.json", b'{"model":"b"}')
        agents_service._sync_sync(BRANCH, [second], prune=False, now=datetime.now(UTC))

        history = agents_service._revisions_sync(first["id"])
        assert [r.revision for r in history] == [2, 1]
        assert history[0].content == '{"model":"b"}'
        # The earlier content is still here — that is the difference between a copy
        # and a backup.
        assert history[1].content == '{"model":"a"}'

    def test_only_the_newest_revision_is_current(self, sqlite_db):
        values = agents_service.prepare(BRANCH, "s.json", b"one")
        agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))
        agents_service._sync_sync(
            BRANCH, [agents_service.prepare(BRANCH, "s.json", b"two")], prune=False,
            now=datetime.now(UTC),
        )

        history = agents_service._revisions_sync(values["id"])
        assert [r.replaced_at is None for r in history] == [True, False]

    def test_a_file_returning_from_removed_adds_no_revision(self, sqlite_db):
        """`_apply` reports 'updated' for a resurrection, and snapshotting that
        would fill the history with duplicates of one content."""
        values = agents_service.prepare(BRANCH, "a.md", b"same")
        other = agents_service.prepare(BRANCH, "b.md", b"other")
        agents_service._sync_sync(BRANCH, [values, other], prune=False, now=datetime.now(UTC))
        agents_service._sync_sync(BRANCH, [other], prune=True, now=datetime.now(UTC))
        agents_service._sync_sync(BRANCH, [values, other], prune=False, now=datetime.now(UTC))

        assert len(agents_service._revisions_sync(values["id"])) == 1

    def test_history_is_capped(self, sqlite_db, monkeypatch):
        """Bounded on purpose: after blobs, this is the second thing here that would
        otherwise grow forever with nothing pruning it."""
        from brownbear.config import get_settings

        monkeypatch.setattr(get_settings(), "config_revisions_kept", 3, raising=False)
        identifier = None
        for n in range(6):
            values = agents_service.prepare(BRANCH, "s.json", f"content {n}".encode())
            identifier = values["id"]
            agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))

        history = agents_service._revisions_sync(identifier)
        assert [r.revision for r in history] == [6, 5, 4]
        assert history[0].content == "content 5"

    def test_deleting_a_file_takes_its_history(self, sqlite_db):
        values = agents_service.prepare(BRANCH, "s.json", b"one")
        agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))
        agents_service._sync_sync(
            BRANCH, [agents_service.prepare(BRANCH, "s.json", b"two")], prune=False,
            now=datetime.now(UTC),
        )

        agents_service._delete_sync(values["id"])
        assert agents_service._revisions_sync(values["id"]) == []


class TestRestorability:
    """The refusal is data, not a rule each client is trusted to reimplement."""

    def test_clean_text_can_be_written_back(self):
        assert agents_service.restorability(ConfigContentKind.text, 0)["restorable"] is True

    def test_a_masked_file_cannot(self):
        verdict = agents_service.restorability(ConfigContentKind.text, 2)
        assert verdict["restorable"] is False
        assert "looks right and does not work" in verdict["reason"]

    def test_content_that_was_never_stored_cannot(self):
        for kind in (ConfigContentKind.binary, ConfigContentKind.too_large):
            assert agents_service.restorability(kind, 0)["restorable"] is False


class TestPullApi:
    def test_returns_content_and_marks_what_cannot_be_restored(self, client, monkeypatch):
        rows = [
            FakeRow(
                id="a_1", machine="laptop", scope_kind="global", project="", tool="claude",
                path="settings.json", sha256="a" * 64, size_bytes=10, content='{"model":"x"}',
                content_kind=ConfigContentKind.text, redactions=0, status=ConfigStatus.synced,
                revision=2, first_seen_at=None, last_synced_at=None, changed_at=None,
                removed_at=None,
            ),
            FakeRow(
                id="a_2", machine="laptop", scope_kind="global", project="", tool="claude",
                path="settings.local.json", sha256="b" * 64, size_bytes=20,
                content='{"env": {"KEY": "«redacted»"}}', content_kind=ConfigContentKind.text,
                redactions=1, status=ConfigStatus.synced, revision=1, first_seen_at=None,
                last_synced_at=None, changed_at=None, removed_at=None,
            ),
        ]
        monkeypatch.setattr(agents_service, "_list_sync", lambda **kwargs: (rows, len(rows)))

        body = client.get(
            "/ext/agents/pull", params={"machine": "laptop", "scope": "global", "tool": "claude"}
        ).json()

        assert body["restorable"] == 1
        assert body["not_restorable"] == 1
        masked = next(f for f in body["files"] if f["path"] == "settings.local.json")
        assert masked["restorable"] is False and "masked" in masked["reason"]
        assert next(f for f in body["files"] if f["path"] == "settings.json")["content"]

    def test_removed_files_are_excluded_unless_asked_for(self, client, monkeypatch):
        row = FakeRow(
            id="a_3", machine="laptop", scope_kind="global", project="", tool="claude",
            path="gone.md", sha256="c" * 64, size_bytes=5, content="bye",
            content_kind=ConfigContentKind.text, redactions=0, status=ConfigStatus.removed,
            revision=1, first_seen_at=None, last_synced_at=None, changed_at=None,
            removed_at=None,
        )
        monkeypatch.setattr(agents_service, "_list_sync", lambda **kwargs: ([row], 1))

        default = client.get(
            "/ext/agents/pull", params={"machine": "laptop", "scope": "global", "tool": "claude"}
        ).json()
        assert default["files"] == []
        assert "include_removed" in default["excluded"][0]["reason"]

        asked = client.get(
            "/ext/agents/pull",
            params={"machine": "laptop", "scope": "global", "tool": "claude",
                    "include_removed": "true"},
        ).json()
        assert [f["path"] for f in asked["files"]] == ["gone.md"]

    def test_an_unknown_tool_is_still_refused(self, client):
        response = client.get(
            "/ext/agents/pull", params={"machine": "laptop", "scope": "global", "tool": "emacs"}
        )
        assert response.status_code == 422


class TestRevisionApi:
    def test_lists_history_without_content(self, client, monkeypatch, sqlite_db):
        values = agents_service.prepare(BRANCH, "s.json", b"one")
        agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))
        agents_service._sync_sync(
            BRANCH, [agents_service.prepare(BRANCH, "s.json", b"two")], prune=False,
            now=datetime.now(UTC),
        )

        body = client.get(f"/ext/agents/files/{values['id']}/revisions").json()
        assert body["current_revision"] == 2
        assert [r["revision"] for r in body["revisions"]] == [2, 1]
        assert all("content" not in r for r in body["revisions"])
        assert body["revisions"][0]["current"] is True

    def test_one_revision_carries_its_content(self, client, sqlite_db):
        values = agents_service.prepare(BRANCH, "s.json", b"one")
        agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))
        agents_service._sync_sync(
            BRANCH, [agents_service.prepare(BRANCH, "s.json", b"two")], prune=False,
            now=datetime.now(UTC),
        )

        body = client.get(f"/ext/agents/files/{values['id']}/revisions/1").json()
        assert body["content"] == "one"
        assert body["current"] is False
        assert body["restorable"] is True

    def test_missing_file_and_missing_revision_are_both_404(self, client, sqlite_db):
        assert client.get("/ext/agents/files/a_nope/revisions").status_code == 404
        values = agents_service.prepare(BRANCH, "s.json", b"one")
        agents_service._sync_sync(BRANCH, [values], prune=False, now=datetime.now(UTC))
        assert client.get(f"/ext/agents/files/{values['id']}/revisions/9").status_code == 404
