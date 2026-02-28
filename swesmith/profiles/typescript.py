"""
TypeScript Repository Profiles for SWE-smith.

This module provides TypeScriptProfile base class and specific repository profiles
for TypeScript projects. TypeScriptProfile inherits from JavaScriptProfile to reuse
Dockerfile templates, test log parsers, and other JavaScript-specific functionality.

test_cmd Design Principle (aligned with Python profiles and original JS profiles):
===================================================================================
NEVER use generic `npm test` -- it is almost always a chain command in TS repos
(lint && type-check && test && docs), where any non-test step failing breaks everything.

Preferred patterns (in order of safety):
  1. `npm run <specific-test-script>` -- uses the project's own script that directly
     invokes the test runner. e.g. `npm run test:vitest`, `yarn test:ts-jest`.
     This is the DOMINANT pattern in the original JS profiles (29/81 profiles).
  2. `./node_modules/.bin/<runner>` -- directly calls the local binary. Fails fast
     if not installed. Used by 4 original JS profiles.
  3. `yarn <runner>` / `pnpm <runner>` -- calls via package manager. Used by 10/3
     original JS profiles.

AVOID:
  - `npm test -- --verbose` -- runs the full chain, 28/81 original JS profiles use
    this but it causes failures when chains include lint/dtslint/docs steps.
  - `npx <runner>` -- silently downloads from npm if binary is missing locally,
    potentially running an incompatible version. Only 3/81 original profiles use this.

Created: 2026-02-03
Phase: Phase 1 - TypeScript Environment Construction
"""

from dataclasses import dataclass, field

from swesmith.constants import ENV_NAME
from swesmith.profiles.base import registry
from swesmith.profiles.javascript import (
    JavaScriptProfile,
    parse_log_jest,
    parse_log_vitest,
    parse_log_mocha,
)


# =============================================================================
# TypeScriptProfile Base Class
# =============================================================================

@dataclass
class TypeScriptProfile(JavaScriptProfile):
    """
    Profile for TypeScript repositories.
    
    Inherits all functionality from JavaScriptProfile, including:
    - Dockerfile template functions (npm/yarn/pnpm)
    - Test log parsers (Jest/Vitest/Mocha)
    - Default directory exclusions
    
    Key differences from JavaScriptProfile:
    - Extended file extensions: [".ts", ".tsx", ".js", ".jsx"]
    - Additional directory exclusions for TypeScript artifacts
    
    Dependency Drift Handling:
    - Many TypeScript repositories lack package-lock.json
    - This causes indirect dependencies to update to incompatible versions
    - Set skip_type_check=True if tsc fails due to dependency drift
    - The framework will automatically modify test_cmd to skip type checking
    """

    # Extended file extensions to include TypeScript
    exts: list[str] = field(default_factory=lambda: [".ts", ".tsx", ".js", ".jsx"])
    
    # Generic flag to handle dependency drift issues
    # When True, type checking steps (tsc) will be skipped from test_cmd
    # This is useful when indirect deps require newer TypeScript versions
    skip_type_check: bool = False

    def get_effective_test_cmd(self) -> str:
        """
        Get the effective test command, handling skip_type_check flag.
        
        This provides a GENERIC solution for dependency drift issues:
        - If skip_type_check=True, removes type-checking steps from test_cmd
        - Handles common patterns like 'npm run test:types', 'tsc --noEmit', etc.
        
        Returns:
            Modified test_cmd with type checking steps removed if skip_type_check=True
        """
        if not self.skip_type_check:
            return self.test_cmd
        
        import re
        cmd = self.test_cmd
        
        # Common patterns for type checking in npm scripts
        type_check_patterns = [
            r'\s*&&\s*npm run test:types',      # && npm run test:types
            r'npm run test:types\s*&&\s*',      # npm run test:types &&
            r'\s*&&\s*tsc\s+--noEmit[^&]*',     # && tsc --noEmit ...
            r'tsc\s+--noEmit[^&]*\s*&&\s*',     # tsc --noEmit ... &&
            r'\s*&&\s*yarn\s+typecheck[^&]*',   # && yarn typecheck
            r'yarn\s+typecheck[^&]*\s*&&\s*',   # yarn typecheck &&
        ]
        
        for pattern in type_check_patterns:
            cmd = re.sub(pattern, '', cmd)
        
        # Clean up any double && or leading/trailing &&
        cmd = re.sub(r'\s*&&\s*&&\s*', ' && ', cmd)
        cmd = re.sub(r'^\s*&&\s*', '', cmd)
        cmd = re.sub(r'\s*&&\s*$', '', cmd)
        
        return cmd.strip()

    def get_test_cmd(self, instance: dict, f2p_only: bool = False) -> tuple[str, list]:
        """
        Override to use get_effective_test_cmd for handling skip_type_check.
        
        This makes the dependency drift handling GENERIC - any TypeScript profile
        can simply set skip_type_check=True and the type checking steps will be
        automatically removed from test_cmd.
        """
        # Get effective test command (with type check removed if skip_type_check=True)
        effective_cmd = self.get_effective_test_cmd()
        
        # Call parent's logic but with modified test_cmd
        original_test_cmd = self.test_cmd
        self.test_cmd = effective_cmd
        try:
            result = super().get_test_cmd(instance, f2p_only)
        finally:
            self.test_cmd = original_test_cmd
        
        return result

    def extract_entities(
        self,
        dirs_exclude: list[str] = None,
        dirs_include: list[str] = [],
        exclude_tests: bool = True,
        max_entities: int = -1,
    ) -> list:
        """
        Override to add TypeScript-specific directory exclusions.
        
        TypeScript projects often have additional build artifacts that should
        be excluded from entity extraction.
        """
        if dirs_exclude is None:
            # JavaScript default exclusions
            dirs_exclude = [
                "dist",
                "build",
                "node_modules",
                "coverage",
                ".next",
                "out",
                "examples",
                "docs",
                "bin",
                # TypeScript-specific exclusions
                "lib",              # Common TypeScript output directory
                ".tsbuildinfo",     # TypeScript incremental build cache
                "typings",          # Type definition files
                "types",            # Type definition files
                "__generated__",    # Generated code (e.g., GraphQL)
                "esm",              # ES Module output
                "cjs",              # CommonJS output
                "umd",              # UMD output
            ]

        return super().extract_entities(
            dirs_exclude=dirs_exclude,
            dirs_include=dirs_include,
            exclude_tests=exclude_tests,
            max_entities=max_entities,
        )


# =============================================================================
# P0 Priority Repository Profiles (Must Support)
# =============================================================================

@dataclass
class ZodProfile(TypeScriptProfile):
    """
    Profile for colinhacks/zod - TypeScript-first schema validation library.
    
    Repository: https://github.com/colinhacks/zod
    Test Framework: Jest (via ts-jest)
    Package Manager: yarn
    """
    owner: str = "colinhacks"
    repo: str = "zod"
    commit: str = "v3.23.8"  # Stable release tag
    # Zod uses Jest via yarn, not Vitest
    test_cmd: str = "NODE_OPTIONS=--max-old-space-size=4096 yarn test:ts-jest --verbose --runInBand"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
# Install git for cloning
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
# Clone repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Checkout specific commit/tag
RUN git checkout {self.commit}
# Install dependencies (zod uses yarn)
RUN yarn install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        # Zod uses Jest, not Vitest
        return parse_log_jest(log)


@dataclass
class ValibotProfile(TypeScriptProfile):
    """
    Profile for fabian-hiller/valibot - Lightweight schema validation library.
    
    Repository: https://github.com/fabian-hiller/valibot
    Test Framework: Vitest
    Package Manager: npm
    
    package.json "test" script calls vitest directly, so npm run test is safe here.
    """
    owner: str = "fabian-hiller"
    repo: str = "valibot"
    commit: str = "v0.30.0"  # Stable release tag
    # valibot's "test" script is just "vitest" (no chain), safe to use npm run
    test_cmd: str = "npm run test -- --reporter verbose"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN npm install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class SuperstructProfile(TypeScriptProfile):
    """
    Profile for ianstormtaylor/superstruct - Data structure validation.
    
    Repository: https://github.com/ianstormtaylor/superstruct
    Test Framework: Vitest
    Package Manager: npm
    
    Note: skip_type_check=True because the repository lacks package-lock.json,
    causing dependency drift. The `@types/expect` stub pulls in latest `jest-mock`
    which requires TypeScript 5.2+ for `ESNext.Disposable`, but repo uses TS 4.8.
    """
    owner: str = "ianstormtaylor"
    repo: str = "superstruct"
    commit: str = "main"  # Use main branch
    test_cmd: str = "npm run build && npm run test:types && npm run test:vitest"
    # GENERIC FLAG: Skip type checking due to dependency drift issue
    skip_type_check: bool = True

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


# =============================================================================
# P1 Priority Repository Profiles (Recommended Support)
# =============================================================================

@dataclass
class CheerioProfile(TypeScriptProfile):
    """
    Profile for cheeriojs/cheerio - Fast, flexible HTML/XML parser.
    
    Repository: https://github.com/cheeriojs/cheerio
    Test Framework: Jest
    Package Manager: npm
    
    Note: directly call jest to avoid potential npm test chain issues.
    """
    owner: str = "cheeriojs"
    repo: str = "cheerio"
    commit: str = "main"
    # Use ./node_modules/.bin/ to fail fast if jest not installed (avoids npx download)
    test_cmd: str = "./node_modules/.bin/jest --verbose --no-color"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class IoTsProfile(TypeScriptProfile):
    """
    Profile for gcanti/io-ts - Runtime type validation for TypeScript.
    
    Repository: https://github.com/gcanti/io-ts
    Test Framework: Vitest (same author as fp-ts, migrated to vitest)
    Package Manager: npm
    
    Note: Same author as fp-ts (gcanti), same npm test chain pattern.
    Directly calling vitest to avoid dtslint/lint chain failures.
    """
    owner: str = "gcanti"
    repo: str = "io-ts"
    commit: str = "master"
    # io-ts has "vitest" script that runs "vitest run" directly (no chain)
    test_cmd: str = "npm run vitest -- --reporter verbose"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        # FIXED: io-ts uses vitest (same ecosystem as fp-ts)
        return parse_log_vitest(log)


@dataclass
class NeverthrowProfile(TypeScriptProfile):
    """
    Profile for supermacro/neverthrow - Type-safe error handling.
    
    Repository: https://github.com/supermacro/neverthrow
    Test Framework: Vitest
    Package Manager: npm
    
    Note: directly call vitest to avoid potential npm test chain issues.
    """
    owner: str = "supermacro"
    repo: str = "neverthrow"
    commit: str = "main"
    # Use ./node_modules/.bin/ to fail fast if vitest not installed
    test_cmd: str = "./node_modules/.bin/vitest run --reporter verbose"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


# =============================================================================
# P2 Priority Repository Profiles (Extended Support)
# =============================================================================

@dataclass
class YupProfile(TypeScriptProfile):
    """
    Profile for jquense/yup - Schema validation library.
    
    Repository: https://github.com/jquense/yup
    Test Framework: Jest
    Package Manager: npm
    
    Note: directly call jest to avoid potential npm test chain issues.
    """
    owner: str = "jquense"
    repo: str = "yup"
    commit: str = "master"
    # Use ./node_modules/.bin/ to fail fast if jest not installed
    test_cmd: str = "./node_modules/.bin/jest --verbose --no-color"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class FpTsProfile(TypeScriptProfile):
    """
    Profile for gcanti/fp-ts - Functional programming library.
    
    Repository: https://github.com/gcanti/fp-ts
    Test Framework: Vitest (NOT Jest - the repo migrated to vitest)
    Package Manager: npm
    
    Note: npm test is a 5-step chain (lint && prettier && dtslint && vitest && docs).
    dtslint fails due to TS 5.5 deprecating target:ES5 in tsconfig.json.
    We bypass this by directly calling vitest.
    """
    owner: str = "gcanti"
    repo: str = "fp-ts"
    commit: str = "master"
    # fp-ts has "vitest" script that runs "vitest run" directly (no chain)
    # DO NOT use "npm test" -- it's a 5-step chain that breaks at dtslint
    test_cmd: str = "npm run vitest -- --reporter verbose"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        # FIXED: fp-ts uses vitest, not jest
        return parse_log_vitest(log)


# =============================================================================
# Registry Registration
# =============================================================================

# Register all TypeScript profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, TypeScriptProfile)
        and obj.__name__ != "TypeScriptProfile"
    ):
        registry.register_profile(obj)
