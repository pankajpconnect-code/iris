"""Disk persistence for named API-console environments.

An environment is a small JSON file (`<slug>.json`) holding {"name", "vars"}.
Reuses collection_store's slugify/atomic-write/secret-pattern helpers rather
than duplicating them — an environment is just a named vars bag, so its own
class stays intentionally thin instead of forcing a shared base class with
CollectionStore (which also owns a requests[] list and richer CRUD).
"""

import json
import os

import collection_store
import keychain


class EnvironmentNotFound(ValueError):
    """Raised when a slug has no environment file on disk."""


class EnvironmentCorrupted(ValueError):
    """Raised when an environment file exists but isn't valid JSON.

    Subclasses ValueError so a generic `except ValueError` still works, but
    callers should catch this separately to avoid reporting corruption as a
    plain 404 "not found" (mirrors collection_store.CollectionCorrupted).
    """


def merge_variables(collection_vars, environment_vars):
    """Environment variables take precedence over collection variables for
    the same key. Non-mutating."""
    merged = dict(collection_vars or {})
    merged.update(environment_vars or {})
    return merged


class EnvironmentStore:
    def __init__(self, root_dir, keychain_backend=keychain):
        self.root = root_dir
        os.makedirs(self.root, exist_ok=True)
        # Secret-named variables (token/secret/password/cookie) are never
        # written to any JSON file. They persist to the macOS Keychain (see
        # keychain.py) and are cached here in memory for the rest of this
        # session so every lookup doesn't shell out to `security`. Only the
        # secret *names* (never values) are persisted in the environment
        # JSON's "secretVarNames" list, so a relaunch knows which Keychain
        # items to look up. If the Keychain is unavailable (non-macOS, or a
        # `security` call fails), secrets fall back to memory-only for the
        # session — the original behaviour — rather than raising.
        self._secret_vars = {}
        self._keychain = keychain_backend

    def _path(self, slug):
        return os.path.join(self.root, f"{slug}.json")

    def _read_json(self, path, corrupt_message):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise EnvironmentCorrupted(corrupt_message.format(exc=exc)) from exc

    def create(self, name):
        slug = collection_store.slugify(name)
        path = self._path(slug)
        if os.path.isfile(path):
            raise ValueError(f"Environment '{slug}' already exists")
        collection_store._atomic_write_json(path, {"name": name, "vars": {}, "secretVarNames": []})
        return slug

    def list(self):
        summaries = []
        for filename in sorted(os.listdir(self.root)):
            if not filename.endswith(".json"):
                continue
            slug = filename[: -len(".json")]
            try:
                data = self._read_json(self._path(slug), f"Environment '{slug}' is corrupted: {{exc}}")
            except EnvironmentCorrupted as exc:
                summaries.append({"slug": slug, "name": slug, "error": str(exc)})
                continue
            summaries.append({"slug": slug, "name": data.get("name", slug)})
        return summaries

    def get(self, slug):
        path = self._path(slug)
        if not os.path.isfile(path):
            raise EnvironmentNotFound(f"Unknown environment '{slug}'")
        return self._read_json(path, f"Environment '{slug}' is corrupted: {{exc}}")

    def delete(self, slug):
        path = self._path(slug)
        if os.path.isfile(path):
            os.remove(path)
        self._secret_vars.pop(slug, None)

    def _secret_value(self, slug, name):
        """Memory cache first (avoids a `security` shellout per lookup this
        session); falls back to the Keychain for a name this process hasn't
        loaded yet (e.g. right after a relaunch). Returns None, never
        raises, if the Keychain is unavailable or the item is missing."""
        cached = self._secret_vars.get(slug, {})
        if name in cached:
            return cached[name]
        try:
            value = self._keychain.get_secret(slug, name)
        except keychain.KeychainUnavailable:
            value = None
        if value is not None:
            self._secret_vars.setdefault(slug, {})[name] = value
        return value

    def _secret_vars_for(self, slug, data):
        # Union with the in-memory cache, not just the persisted
        # secretVarNames — a name that failed to reach the Keychain is
        # deliberately kept out of secretVarNames (so a restart doesn't
        # claim a value that was never actually written), but it must
        # still resolve for THIS session via the memory-only fallback.
        names = set(data.get("secretVarNames", [])) | set(self._secret_vars.get(slug, {}))
        return {
            name: value
            for name in names
            if (value := self._secret_value(slug, name)) is not None
        }

    def get_vars(self, slug):
        data = self.get(slug)
        merged = dict(data.get("vars", {}))
        merged.update(self._secret_vars_for(slug, data))
        disabled = set(data.get("disabledVars", []))
        return {k: v for k, v in merged.items() if k not in disabled}

    def get_vars_state(self, slug):
        """{name: {"value", "enabled"}} for the environment editor UI — unlike
        get_vars, includes disabled vars (with their stored value) so
        unchecking one doesn't discard it."""
        data = self.get(slug)
        merged = dict(data.get("vars", {}))
        merged.update(self._secret_vars_for(slug, data))
        disabled = set(data.get("disabledVars", []))
        return {k: {"value": v, "enabled": k not in disabled} for k, v in merged.items()}

    def set_vars(self, slug, variables):
        data = self.get(slug)
        # None means "no value" (e.g. a capture test whose JSON path didn't
        # resolve — assertions.run_assertions still records the attempt with
        # actual=None and passed=False). Persisting that is never correct: for
        # a secret it would reach `security add-generic-password -w None`,
        # which subprocess rejects with a TypeError before the CLI even runs.
        variables = {k: v for k, v in variables.items() if v is not None}
        secret_updates = {k: v for k, v in variables.items() if collection_store._SECRET_NAME_RE.search(k)}
        persist_updates = {k: v for k, v in variables.items() if k not in secret_updates}
        needs_write = False
        if secret_updates:
            self._secret_vars.setdefault(slug, {}).update(secret_updates)
            secret_names = set(data.get("secretVarNames", []))
            for name, value in secret_updates.items():
                try:
                    self._keychain.set_secret(slug, name, value)
                    secret_names.add(name)
                except keychain.KeychainUnavailable:
                    pass  # falls back to memory-only for this session, as before — must not be
                    # recorded in secretVarNames, or a restart would silently lose it while the
                    # on-disk JSON kept claiming it was keychain-backed
            data["secretVarNames"] = sorted(secret_names)
            needs_write = True
        if persist_updates:
            data.setdefault("vars", {}).update(persist_updates)
            needs_write = True
        if needs_write:
            collection_store._atomic_write_json(self._path(slug), data)

    def delete_var(self, slug, name):
        data = self.get(slug)
        self._secret_vars.get(slug, {}).pop(name, None)
        try:
            self._keychain.delete_secret(slug, name)
        except keychain.KeychainUnavailable:
            pass
        secret_names = set(data.get("secretVarNames", []))
        secret_names.discard(name)
        data["secretVarNames"] = sorted(secret_names)
        data.get("vars", {}).pop(name, None)
        disabled = set(data.get("disabledVars", []))
        disabled.discard(name)
        data["disabledVars"] = sorted(disabled)
        collection_store._atomic_write_json(self._path(slug), data)

    def set_var_enabled(self, slug, name, enabled):
        data = self.get(slug)
        disabled = set(data.get("disabledVars", []))
        if enabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        data["disabledVars"] = sorted(disabled)
        collection_store._atomic_write_json(self._path(slug), data)

    def divergence(self):
        """{name: {"secret": bool, "environmentNames": [str, ...]}} for
        every variable name defined (with a value) in 2+ environments
        whose values are not all identical. Never includes a value — only
        which environments define the name, so a caller can never leak a
        secret's contents through this method. Corrupted environments (see
        list()) are skipped rather than raising, so one bad file doesn't
        blank out every other environment's signal."""
        values_by_name = {}
        for summary in self.list():
            if "error" in summary:
                continue
            for name, info in self.get_vars_state(summary["slug"]).items():
                values_by_name.setdefault(name, {})[summary["name"]] = info["value"]
        result = {}
        for name, values_by_env in values_by_name.items():
            if len(values_by_env) < 2:
                continue
            if len(set(values_by_env.values())) < 2:
                continue
            result[name] = {
                "secret": bool(collection_store._SECRET_NAME_RE.search(name)),
                "environmentNames": sorted(values_by_env),
            }
        return result
