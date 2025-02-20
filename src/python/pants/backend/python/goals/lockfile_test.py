# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from textwrap import dedent

from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    RequestedPythonUserResolveNames,
)
from pants.backend.python.goals.lockfile import rules as lockfile_rules
from pants.backend.python.goals.lockfile import setup_user_lockfile_requests
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementTarget
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import GenerateLockfileResult, UserGenerateLockfiles
from pants.engine.fs import DigestContents
from pants.engine.rules import SubsystemRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import strip_prefix


def test_lockfile_generation() -> None:
    rule_runner = RuleRunner(
        rules=[
            *lockfile_rules(),
            *pex.rules(),
            QueryRule(GenerateLockfileResult, [GeneratePythonLockfile]),
        ]
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)

    def generate(*, use_pex: bool) -> str:
        result = rule_runner.request(
            GenerateLockfileResult,
            [
                GeneratePythonLockfile(
                    requirements=FrozenOrderedSet(["ansicolors==1.1.8"]),
                    interpreter_constraints=InterpreterConstraints(),
                    resolve_name="test",
                    lockfile_dest="test.lock",
                    use_pex=use_pex,
                )
            ],
        )
        digest_contents = rule_runner.request(DigestContents, [result.digest])
        assert len(digest_contents) == 1
        return digest_contents[0].content.decode()

    pex_header = dedent(
        """\
        // This lockfile was autogenerated by Pants. To regenerate, run:
        //
        //    ./pants generate-lockfiles --resolve=test
        //
        // --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---
        // {
        //   "version": 2,
        //   "valid_for_interpreter_constraints": [],
        //   "generated_with_requirements": [
        //     "ansicolors==1.1.8"
        //   ]
        // }
        // --- END PANTS LOCKFILE METADATA ---
        """
    )
    pex_lock = generate(use_pex=True)
    assert pex_lock.startswith(pex_header)
    lock_entry = json.loads(strip_prefix(pex_lock, pex_header))
    reqs = lock_entry["locked_resolves"][0]["locked_requirements"]
    assert len(reqs) == 1
    assert reqs[0]["project_name"] == "ansicolors"
    assert reqs[0]["version"] == "1.1.8"

    poetry_lock = generate(use_pex=False)
    assert poetry_lock.startswith("# This lockfile was autogenerated by Pants.")
    assert poetry_lock.rstrip().endswith(
        dedent(
            """\
            ansicolors==1.1.8 \\
                --hash=sha256:00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187 \\
                --hash=sha256:99f94f5e3348a0bcd43c82e5fc4414013ccc19d70bd939ad71e0133ce9c372e0"""
        )
    )


def test_multiple_resolves() -> None:
    rule_runner = RuleRunner(
        rules=[
            setup_user_lockfile_requests,
            SubsystemRule(PythonSetup),
            QueryRule(UserGenerateLockfiles, [RequestedPythonUserResolveNames]),
        ],
        target_types=[PythonRequirementTarget],
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(
                    name='a',
                    requirements=['a'],
                    resolve='a',
                )
                python_requirement(
                    name='b',
                    requirements=['b'],
                    resolve='b',
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--python-resolves={'a': 'a.lock', 'b': 'b.lock'}",
            # Override interpreter constraints for 'b', but use default for 'a'.
            "--python-resolves-to-interpreter-constraints={'b': ['==3.7.*']}",
            "--python-enable-resolves",
            "--python-lockfile-generator=pex",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    result = rule_runner.request(
        UserGenerateLockfiles, [RequestedPythonUserResolveNames(["a", "b"])]
    )
    assert set(result) == {
        GeneratePythonLockfile(
            requirements=FrozenOrderedSet(["a"]),
            interpreter_constraints=InterpreterConstraints(
                PythonSetup.default_interpreter_constraints
            ),
            resolve_name="a",
            lockfile_dest="a.lock",
            use_pex=True,
        ),
        GeneratePythonLockfile(
            requirements=FrozenOrderedSet(["b"]),
            interpreter_constraints=InterpreterConstraints(["==3.7.*"]),
            resolve_name="b",
            lockfile_dest="b.lock",
            use_pex=True,
        ),
    }
