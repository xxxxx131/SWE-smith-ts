"""
TypeScript Repository Profiles for SWE-smith.

This module provides TypeScriptProfile base class and specific repository profiles
for TypeScript projects. TypeScriptProfile inherits from JavaScriptProfile to reuse
Dockerfile templates, test log parsers, and other JavaScript-specific functionality.

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
    test_cmd: str = "yarn test:ts-jest --verbose"

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
    """
    owner: str = "fabian-hiller"
    repo: str = "valibot"
    commit: str = "v0.30.0"  # Stable release tag
    test_cmd: str = "npm test -- --reporter verbose"

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
    """
    owner: str = "cheeriojs"
    repo: str = "cheerio"
    commit: str = "main"
    test_cmd: str = "npm test -- --verbose"

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
    Test Framework: Jest
    Package Manager: npm
    """
    owner: str = "gcanti"
    repo: str = "io-ts"
    commit: str = "master"
    test_cmd: str = "npm test -- --verbose"

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
class NeverthrowProfile(TypeScriptProfile):
    """
    Profile for supermacro/neverthrow - Type-safe error handling.
    
    Repository: https://github.com/supermacro/neverthrow
    Test Framework: Vitest
    Package Manager: npm
    """
    owner: str = "supermacro"
    repo: str = "neverthrow"
    commit: str = "main"
    test_cmd: str = "npm test -- --reporter verbose"

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
    """
    owner: str = "jquense"
    repo: str = "yup"
    commit: str = "master"
    test_cmd: str = "npm test -- --verbose"

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
    Test Framework: Jest
    Package Manager: npm
    """
    owner: str = "gcanti"
    repo: str = "fp-ts"
    commit: str = "master"
    test_cmd: str = "npm test -- --verbose"

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
