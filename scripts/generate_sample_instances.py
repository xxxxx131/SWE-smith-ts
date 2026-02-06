#!/usr/bin/env python3
"""
为 8 个目标 TypeScript 仓库生成样例任务实例

用于 Phase 3 测试和验证流程
"""

import json
from datetime import datetime
from pathlib import Path

# 8 个目标仓库配置
REPOS = [
    {
        "owner": "colinhacks",
        "repo": "zod",
        "commit": "v3.23.8",
        "test_framework": "vitest",
        "test_cmd": "npm test -- --verbose",
        "sample_file": "src/types/string.ts",
        "sample_function": "_validate"
    },
    {
        "owner": "fabian-hiller",
        "repo": "valibot",
        "commit": "v0.30.0",
        "test_framework": "vitest",
        "test_cmd": "npm test -- --reporter verbose",
        "sample_file": "src/schemas/number.ts",
        "sample_function": "parse"
    },
    {
        "owner": "ianstormtaylor",
        "repo": "superstruct",
        "commit": "main",
        "test_framework": "mocha",
        "test_cmd": "npm test -- --reporter spec",
        "sample_file": "src/structs/coercions.ts",
        "sample_function": "coerce"
    },
    {
        "owner": "cheeriojs",
        "repo": "cheerio",
        "commit": "main",
        "test_framework": "jest",
        "test_cmd": "npm test -- --verbose",
        "sample_file": "src/api/manipulation.ts",
        "sample_function": "append"
    },
    {
        "owner": "gcanti",
        "repo": "io-ts",
        "commit": "master",
        "test_framework": "jest",
        "test_cmd": "npm test -- --verbose",
        "sample_file": "src/Decoder.ts",
        "sample_function": "decode"
    },
    {
        "owner": "supermacro",
        "repo": "neverthrow",
        "commit": "main",
        "test_framework": "vitest",
        "test_cmd": "npm test -- --reporter verbose",
        "sample_file": "src/result.ts",
        "sample_function": "map"
    },
    {
        "owner": "jquense",
        "repo": "yup",
        "commit": "master",
        "test_framework": "jest",
        "test_cmd": "npm test -- --verbose",
        "sample_file": "src/string.ts",
        "sample_function": "validate"
    },
    {
        "owner": "gcanti",
        "repo": "fp-ts",
        "commit": "master",
        "test_framework": "jest",
        "test_cmd": "npm test -- --verbose",
        "sample_file": "src/Option.ts",
        "sample_function": "map"
    },
]

PROBLEM_STATEMENT_TEMPLATE = """## Bug Report

There is a bug in `{function_name}` in the file `{file_path}`.

### Failing Tests

The following tests are failing:

{failing_tests}

### Expected Behavior

After fixing the bug, all the above tests should pass.

### How to Reproduce

Run the test suite:

```bash
{test_cmd}
```
"""


def create_sample_instance(repo_config: dict, index: int) -> dict:
    """创建样例任务实例"""
    owner = repo_config["owner"]
    repo = repo_config["repo"]
    commit = repo_config["commit"]
    
    instance_id = f"{owner}__{repo}__{commit}__{index:04d}"
    
    # 生成模拟的失败测试
    failing_tests = f"- `test/{repo_config['sample_function']}.test.ts::should handle edge case`"
    
    problem_statement = PROBLEM_STATEMENT_TEMPLATE.format(
        function_name=repo_config["sample_function"],
        file_path=repo_config["sample_file"],
        failing_tests=failing_tests,
        test_cmd=repo_config["test_cmd"],
    )
    
    return {
        "instance_id": instance_id,
        "repo": f"{owner}/{repo}",
        "base_commit": commit,
        "patch": f"diff --git a/{repo_config['sample_file']} b/{repo_config['sample_file']}\n--- a/{repo_config['sample_file']}\n+++ b/{repo_config['sample_file']}\n@@ -10,1 +10,1 @@\n-    // original code\n+    // buggy code",
        "test_patch": "",
        "problem_statement": problem_statement,
        "hints_text": "",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "FAIL_TO_PASS": [
            f"test/{repo_config['sample_function']}.test.ts::should handle edge case"
        ],
        "PASS_TO_PASS": [
            f"test/{repo_config['sample_function']}.test.ts::should work normally"
        ],
        "environment_setup_commit": commit,
        "language": "typescript",
        "test_framework": repo_config["test_framework"],
        "package_manager": "npm",
        "node_version": "20",
        "modifier": "sample_modifier",
        "entity": {
            "name": repo_config["sample_function"],
            "file_path": repo_config["sample_file"],
            "line_start": 10,
            "line_end": 25
        }
    }


def main():
    output_base = Path("/data/k8s/yrx/SWE-smith/files/TS")
    
    all_instances = []
    
    for repo_config in REPOS:
        owner = repo_config["owner"]
        repo = repo_config["repo"]
        repo_dir = output_base / f"{owner}__{repo}"
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        # 为每个仓库生成 2 个样例实例
        for i in range(1, 3):
            instance = create_sample_instance(repo_config, i)
            
            # 保存实例
            file_path = repo_dir / f"{instance['instance_id']}.json"
            file_path.write_text(
                json.dumps(instance, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            all_instances.append({
                "instance_id": instance["instance_id"],
                "repo": instance["repo"],
                "file": str(file_path.relative_to(output_base))
            })
            
            print(f"✅ 创建: {file_path.name}")
    
    # 创建索引文件
    index = {
        "version": "1.0.0",
        "description": "TypeScript 任务实例索引 - 8 个目标仓库",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "language": "typescript",
        "instances": all_instances,
        "total_count": len(all_instances),
        "repositories": [f"{r['owner']}/{r['repo']}" for r in REPOS]
    }
    
    index_path = output_base / "index.json"
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"\n✅ 索引: {index_path}")
    print(f"📊 总计: {len(all_instances)} 个任务实例")


if __name__ == "__main__":
    main()
