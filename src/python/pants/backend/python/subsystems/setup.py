# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import logging
import os
from typing import Iterable, Iterator, Optional, cast

from pants.base.deprecated import warn_or_error
from pants.option.option_types import (
    BoolOption,
    DictOption,
    EnumOption,
    FileOption,
    StrListOption,
    StrOption,
)
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name, doc_url
from pants.util.memo import memoized_property
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@enum.unique
class InvalidLockfileBehavior(enum.Enum):
    error = "error"
    ignore = "ignore"
    warn = "warn"


@enum.unique
class LockfileGenerator(enum.Enum):
    PEX = "pex"
    POETRY = "poetry"


class PythonSetup(Subsystem):
    options_scope = "python"
    help = "Options for Pants's Python backend."

    default_interpreter_constraints = ["CPython>=3.7,<4"]
    default_interpreter_universe = ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11"]

    interpreter_constraints = StrListOption(
        "--interpreter-constraints",
        default=default_interpreter_constraints,
        help=(
            "The Python interpreters your codebase is compatible with.\n\nSpecify with "
            "requirement syntax, e.g. 'CPython>=2.7,<3' (A CPython interpreter with version "
            ">=2.7 AND version <3) or 'PyPy' (A pypy interpreter of any version). Multiple "
            "constraint strings will be ORed together.\n\nThese constraints are used as the "
            "default value for the `interpreter_constraints` field of Python targets."
        ),
        advanced=True,
        metavar="<requirement>",
    )
    interpreter_universe = StrListOption(
        "--interpreter-versions-universe",
        default=default_interpreter_universe,
        help=(
            "All known Python major/minor interpreter versions that may be used by either "
            "your code or tools used by your code.\n\n"
            "This is used by Pants to robustly handle interpreter constraints, such as knowing "
            "when generating lockfiles which Python versions to check if your code is "
            "using.\n\n"
            "This does not control which interpreter your code will use. Instead, to set your "
            "interpreter constraints, update `[python].interpreter_constraints`, the "
            "`interpreter_constraints` field, and relevant tool options like "
            "`[isort].interpreter_constraints` to tell Pants which interpreters your code "
            f"actually uses. See {doc_url('python-interpreter-compatibility')}.\n\n"
            "All elements must be the minor and major Python version, e.g. '2.7' or '3.10'. Do "
            "not include the patch version.\n\n"
        ),
        advanced=True,
    )
    requirement_constraints = FileOption(
        "--requirement-constraints",
        default=None,
        help=(
            "When resolving third-party requirements for your own code (vs. tools you run), "
            "use this constraints file to determine which versions to use.\n\n"
            "This only applies when resolving user requirements, rather than tools you run "
            "like Black and Pytest. To constrain tools, set `[tool].lockfile`, e.g. "
            "`[black].lockfile`.\n\n"
            "See https://pip.pypa.io/en/stable/user_guide/#constraints-files for more "
            "information on the format of constraint files and how constraints are applied in "
            "Pex and pip.\n\n"
            "Mutually exclusive with `[python].enable_resolves`."
        ),
        advanced=True,
        mutually_exclusive_group="lockfile",
    )
    resolve_all_constraints = BoolOption(
        "--resolve-all-constraints",
        default=True,
        help=(
            "If enabled, when resolving requirements, Pants will first resolve your entire "
            "constraints file as a single global resolve. Then, if the code uses a subset of "
            "your constraints file, Pants will extract the relevant requirements from that "
            "global resolve so that only what's actually needed gets used. If disabled, Pants "
            "will not use a global resolve and will resolve each subset of your requirements "
            "independently."
            "\n\nUsually this option should be enabled because it can result in far fewer "
            "resolves."
            "\n\nRequires [python].requirement_constraints to be set."
        ),
        advanced=True,
    )
    enable_resolves = BoolOption(
        "--enable-resolves",
        default=False,
        help=(
            "Set to true to enable the multiple resolves mechanism. See "
            "`[python].resolves` for an explanation of this feature.\n\n"
            "Warning: the `generate-lockfiles` goal does not yet work if you have VCS (Git) "
            "requirements and local requirements. Support is coming in a future Pants release. You "
            "can still use multiple resolves, but you must manually generate your lockfiles rather "
            "than using the `generate-lockfiles` goal, e.g. by running `pip freeze`. Specifically, "
            "set up `[python].resolves` to point to your manually generated lockfile paths, and "
            "then set `[python].resolves_generate_lockfiles = false` in `pants.toml`.\n\n"
            "You may also run into issues generating lockfiles when using Poetry as the generator, "
            "rather than Pex. See the option `[python].lockfile_generator` for more "
            "information.\n\n"
            "The resolves feature offers three major benefits compared to "
            "`[python].requirement_constraints`:\n\n"
            "  1. Uses `--hash` to validate that all downloaded files are expected, which "
            "reduces the risk of supply chain attacks.\n"
            "  2. Enforces that all transitive dependencies are in the lockfile, whereas "
            "constraints allow you to leave off dependencies. This ensures your build is more "
            "stable and reduces the risk of supply chain attacks.\n"
            "  3. Allows you to have multiple resolves in your repository.\n\n"
            "Mutually exclusive with `[python].requirement_constraints`."
        ),
        advanced=True,
        mutually_exclusive_group="lockfile",
    )
    resolves = DictOption[str](
        "--resolves",
        default={"python-default": "3rdparty/python/default.lock"},
        help=(
            "A mapping of logical names to lockfile paths used in your project.\n\n"
            "Many organizations only need a single resolve for their whole project, which is "
            "a good default and the simplest thing to do. However, you may need multiple "
            "resolves, such as if you use two conflicting versions of a requirement in "
            "your repository.\n\n"
            "For now, Pants only has first-class support for disjoint resolves, meaning that "
            "you cannot ergonomically set a `python_requirement` or `python_source` target, "
            "for example, to work with multiple resolves. Practically, this means that you "
            "cannot yet ergonomically reuse common code, such as util files, across projects "
            "using different resolves. Support for overlapping resolves is coming in Pants 2.11 "
            "through a new 'parametrization' feature.\n\n"
            f"If you only need a single resolve, run `{bin_name()} generate-lockfiles` to "
            "generate the lockfile.\n\n"
            "If you need multiple resolves:\n\n"
            "  1. Via this option, define multiple resolve "
            "names and their lockfile paths. The names should be meaningful to your "
            "repository, such as `data-science` or `pants-plugins`.\n"
            "  2. Set the default with `[python].default_resolve`.\n"
            "  3. Update your `python_requirement` targets with the "
            "`resolve` field to declare which resolve they should "
            "be available in. They default to `[python].default_resolve`, so you "
            "only need to update targets that you want in non-default resolves. "
            "(Often you'll set this via the `python_requirements` or `poetry_requirements` "
            "target generators)\n"
            f"  4. Run `{bin_name()} generate-lockfiles` to generate the lockfiles. If the results "
            "aren't what you'd expect, adjust the prior step.\n"
            "  5. Update any targets like `python_source` / `python_sources`, "
            "`python_test` / `python_tests`, and `pex_binary` which need to set a non-default "
            "resolve with the `resolve` field.\n\n"
            "You can name the lockfile paths what you would like; Pants does not expect a "
            "certain file extension or location.\n\n"
            "Only applies if `[python].enable_resolves` is true."
        ),
        advanced=True,
    )
    default_resolve = StrOption(
        "--default-resolve",
        default="python-default",
        help=(
            "The default value used for the `resolve` field.\n\n"
            "The name must be defined as a resolve in `[python].resolves`."
        ),
        advanced=True,
    )
    _resolves_to_interpreter_constraints = DictOption["list[str]"](
        "--resolves-to-interpreter-constraints",
        help=(
            "Override the interpreter constraints to use when generating a resolve's lockfile "
            "with the `generate-lockfiles` goal.\n\n"
            "By default, each resolve from `[python].resolves` will use your "
            "global interpreter constraints set in `[python].interpreter_constraints`. With "
            "this option, you can override each resolve to use certain interpreter "
            "constraints, such as `{'data-science': ['==3.8.*']}`.\n\n"
            "Pants will validate that the interpreter constraints of your code using a "
            "resolve are compatible with that resolve's own constraints. For example, if your "
            "code is set to use ['==3.9.*'] via the `interpreter_constraints` field, but it's "
            "also using a resolve whose interpreter constraints are set to ['==3.7.*'], then "
            "Pants will error explaining the incompatibility.\n\n"
            "The keys must be defined as resolves in `[python].resolves`."
        ),
        advanced=True,
    )
    invalid_lockfile_behavior = EnumOption(
        "--invalid-lockfile-behavior",
        default=InvalidLockfileBehavior.error,
        help=(
            "The behavior when a lockfile has requirements or interpreter constraints that are "
            "not compatible with what the current build is using.\n\n"
            "We recommend keeping the default of `error` for CI builds.\n\n"
            "Note that `warn` will still expect a Pants lockfile header, it only won't error if "
            "the lockfile is stale and should be regenerated. Use `ignore` to avoid needing a "
            "lockfile header at all, e.g. if you are manually managing lockfiles rather than "
            "using the `generate-lockfiles` goal."
        ),
        advanced=True,
    )
    _lockfile_generator = EnumOption(
        "--lockfile-generator",
        default=LockfileGenerator.POETRY,
        help=(
            "Whether to use Pex or Poetry with the `generate-lockfiles` goal.\n\n"
            "Poetry does not work with `[python-repos]` for custom indexes/cheeseshops. If you use "
            "this feature, you should use Pex.\n\n"
            "Several users have also had issues with how Poetry's lockfile generation handles "
            "environment markers for transitive dependencies; certain dependencies end up with "
            "nonsensical environment markers which cause the dependency to not be installed, then "
            "for Pants/Pex to complain the dependency is missing, even though it's in the "
            "lockfile. There is a workaround: for `[python].resolves`, manually create a "
            "`python_requirement` target for the problematic transitive dependencies so that they "
            "are seen as direct requirements, rather than transitive. For tool lockfiles, add the "
            "problematic transitive dependency to `[tool].extra_requirements`, e.g. "
            "`[isort].extra_requirements`. Then, regenerate the lockfile(s) with the "
            "`generate-lockfiles` goal. Alternatively, use Pex for generation.\n\n"
            "Finally, installing from a Poetry-generated lockfile is slower than installing from a "
            "Pex lockfile.\n\n"
            "However, Pex lockfile generation is a new feature. Given how vast the Python packaging "
            "ecosystem is, it is possible you may experience edge cases / bugs we haven't yet "
            "covered. Bug reports are appreciated! "
            "https://github.com/pantsbuild/pants/issues/new/choose\n\n"
            "Note that while Pex generates locks in a proprietary JSON format, you can use the "
            f"`{bin_name()} export` goal for Pants to create a virtual environment for "
            f"interoperability with tools like IDEs."
        ),
    )
    resolves_generate_lockfiles = BoolOption(
        "--resolves-generate-lockfiles",
        default=True,
        help=(
            "If False, Pants will not attempt to generate lockfiles for `[python].resolves` when "
            "running the `generate-lockfiles` goal.\n\n"
            "This is intended to allow you to manually generate lockfiles as a workaround for the "
            "issues described in the `[python].enable_resolves` option.\n\n"
            "If you set this to False, Pants will not attempt to validate the metadata headers "
            "for your user lockfiles. This is useful so that you can keep "
            "`[python].invalid_lockfile_behavior` to `error` or `warn` if you'd like so that tool "
            "lockfiles continue to be validated, while user lockfiles are skipped."
        ),
        advanced=True,
    )
    run_against_entire_lockfile = BoolOption(
        "--run-against-entire-lockfile",
        default=False,
        help=(
            "If enabled, when running binaries, tests, and repls, Pants will use the entire "
            "lockfile/constraints file instead of just the relevant subset. This can improve "
            "performance and reduce cache size, but has two consequences: 1) All cached test "
            "results will be invalidated if any requirement in the lockfile changes, rather "
            "than just those that depend on the changed requirement. 2) Requirements unneeded "
            "by a test/run/repl will be present on the sys.path, which might in rare cases "
            "cause their behavior to change.\n\n"
            "This option does not affect packaging deployable artifacts, such as "
            "PEX files, wheels and cloud functions, which will still use just the exact "
            "subset of requirements needed."
        ),
        advanced=True,
    )
    resolver_manylinux = StrOption(
        "--resolver-manylinux",
        default="manylinux2014",
        help="Whether to allow resolution of manylinux wheels when resolving requirements for "
        "foreign linux platforms. The value should be a manylinux platform upper bound, "
        "e.g.: 'manylinux2010', or else the string 'no' to disallow.",
        advanced=True,
    )
    tailor_ignore_solitary_init_files = BoolOption(
        "--tailor-ignore-solitary-init-files",
        default=True,
        help="Don't tailor `python_sources` targets for solitary `__init__.py` files, as "
        "those usually exist as import scaffolding rather than true library code.\n\n"
        "Set to False if you commonly have packages containing real code in "
        "`__init__.py` and there are no other .py files in the package.",
        advanced=True,
    )
    tailor_requirements_targets = BoolOption(
        "--tailor-requirements-targets",
        default=True,
        help="Tailor python_requirements() targets for requirements files.",
        advanced=True,
    )
    tailor_pex_binary_targets = BoolOption(
        "--tailor-pex-binary-targets",
        default=True,
        help="Tailor pex_binary() targets for Python entry point files.",
        advanced=True,
    )
    macos_big_sur_compatibility = BoolOption(
        "--macos-big-sur-compatibility",
        default=False,
        help="If set, and if running on MacOS Big Sur, use macosx_10_16 as the platform "
        "when building wheels. Otherwise, the default of macosx_11_0 will be used. "
        "This may be required for pip to be able to install the resulting distribution "
        "on Big Sur.",
    )

    @property
    def generate_lockfiles_with_pex(self) -> bool:
        """Else, generate with Poetry."""
        if self.options.is_default("lockfile_generator"):
            warn_or_error(
                "2.12.0.dev0",
                "`[python].lockfile_generator` defaulting to 'poetry'",
                softwrap(
                    f"""
                    In Pants 2.12, Pants will default to using Pex to generate lockfiles
                    with the `generate-lockfiles` goal, rather than Poetry. Run
                    `{bin_name()} help-advanced python` for more information on the benefits and
                    possible issues with switching to Pex.

                    To keep using Poetry, set `[python].lockfile_generator = 'poetry'` in
                    pants.toml. To try Pex, set to 'pex'.

                    Note that you can incrementally switch to Pex lockfiles if you want to reduce
                    risk while migrating. The option `[python].lockfile_generator` only impacts
                    how Pants generates new lockfiles; you can continue to use
                    requirements.txt-style lockfiles (i.e. those generated by Poetry) even if
                    new lockfiles are generated in Pex's JSON format. For example, you can run
                    `{bin_name()} --python-lockfile-generator=pex generate-lockfiles
                    --resolve=isort` to only regenerate the isort lockfile.
                    """
                ),
            )

        return self._lockfile_generator == LockfileGenerator.PEX

    @memoized_property
    def resolves_to_interpreter_constraints(self) -> dict[str, tuple[str, ...]]:
        result = {}
        for resolve, ics in self._resolves_to_interpreter_constraints.items():
            if resolve not in self.resolves:
                raise KeyError(
                    "Unrecognized resolve name in the option "
                    f"`[python].resolves_to_interpreter_constraints`: {resolve}. Each "
                    "key must be one of the keys in `[python].resolves`: "
                    f"{sorted(self.resolves.keys())}"
                )
            result[resolve] = tuple(ics)
        return result

    def resolve_all_constraints_was_set_explicitly(self) -> bool:
        return not self.options.is_default("resolve_all_constraints")

    @property
    def manylinux(self) -> str | None:
        manylinux = cast(Optional[str], self.resolver_manylinux)
        if manylinux is None or manylinux.lower() in ("false", "no", "none"):
            return None
        return manylinux

    @property
    def manylinux_pex_args(self) -> Iterator[str]:
        if self.manylinux:
            yield "--manylinux"
            yield self.manylinux
        else:
            yield "--no-manylinux"

    @property
    def scratch_dir(self):
        return os.path.join(self.options.pants_workdir, *self.options_scope.split("."))

    def compatibility_or_constraints(self, compatibility: Iterable[str] | None) -> tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        if self.options.is_flagged("interpreter_constraints"):
            return self.interpreter_constraints
        return tuple(compatibility or self.interpreter_constraints)

    def compatibilities_or_constraints(
        self, compatibilities: Iterable[Iterable[str] | None]
    ) -> tuple[str, ...]:
        return tuple(
            constraint
            for compatibility in compatibilities
            for constraint in self.compatibility_or_constraints(compatibility)
        )
