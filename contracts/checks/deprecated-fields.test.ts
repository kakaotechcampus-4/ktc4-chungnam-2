/**
 * 스펙에서 deprecated인 필드를 화면이 쓰면 실패한다(#1467, 멘토 리뷰).
 *
 * 서버가 칸을 바꾸면(#1385 도보 분 → m) 옛 칸은 호환용으로 남고 화면이 새 칸으로 옮겨 가야 한다. 옛 칸이 스펙에 글로만
 * "곧 없앤다"로 적혀 있으면 생성 타입도 CI도 몰라서 화면이 옛 칸을 계속 썼다(반경 넓히기 확인 창).
 *
 * - 스펙(`docs/api-spec.yaml`)에서 `deprecated: true`인 속성과 파라미터의 이름을 모은다.
 * - `frontend/src`에서 그 이름이 나오는 곳을 찾는다.
 * - 화면이 쓰는 deprecated 필드는 `docs/openapi-workflow.md` 「화면이 아직 쓰는 deprecated 필드」 표에 FE 이슈 번호와 함께 있어야 한다.
 * - 표의 줄이 실제와 다르면(이제 쓰지 않거나 스펙에서 deprecated가 아니면) 실패한다. 표는 비어 가는 것이 정상이다.
 *
 * 이름으로 찾으니 흔한 이름(id, name)이 deprecated가 되면 다른 곳까지 걸린다. 그때 찾는 방법을 좁힌다.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { load } from "js-yaml";
import { describe, expect, it } from "vitest";

const REPO = fileURLToPath(new URL("../..", import.meta.url));
const SPEC = join(REPO, "docs/api-spec.yaml");
const WORKFLOW = join(REPO, "docs/openapi-workflow.md");
const FRONTEND_SRC = join(REPO, "frontend/src");
const TABLE_HEADING = "### 화면이 아직 쓰는 deprecated 필드";
const SOURCE = /\.(ts|tsx|js|jsx)$/;

type Node = Record<string, unknown>;

/** 스펙 안의 deprecated 속성(`properties` 아래)과 파라미터(`in`과 `name`이 있는 것) 이름 → 스펙 안 위치들. */
export function collectDeprecated(spec: unknown): Map<string, string[]> {
  const found = new Map<string, string[]>();
  const add = (name: string, where: string) => found.set(name, [...(found.get(name) ?? []), where]);
  const walk = (value: unknown, path: string) => {
    if (Array.isArray(value)) return value.forEach((v, i) => walk(v, `${path}[${i}]`));
    if (!value || typeof value !== "object") return;
    const node = value as Node;
    if (node.deprecated === true && typeof node.name === "string" && typeof node.in === "string") add(node.name, path);
    if (node.properties && typeof node.properties === "object") {
      for (const [name, schema] of Object.entries(node.properties as Node)) {
        if ((schema as Node | null)?.deprecated === true) add(name, `${path}.properties.${name}`);
      }
    }
    for (const [key, child] of Object.entries(node)) walk(child, path ? `${path}.${key}` : key);
  };
  walk(spec, "");
  return found;
}

/** `docs/openapi-workflow.md` 표의 줄: 필드 이름 → FE 이슈 번호(없으면 빈 문자열). */
export function readKnownTable(markdown: string): Map<string, string> {
  const start = markdown.indexOf(TABLE_HEADING);
  if (start < 0) throw new Error(`docs/openapi-workflow.md에 「${TABLE_HEADING.slice(4)}」 절이 없다`);
  const body = markdown.slice(start + TABLE_HEADING.length).split(/^#{2,3} /m)[0];
  const rows = new Map<string, string>();
  for (const [, name, rest] of body.matchAll(/^\|\s*`([A-Za-z0-9_]+)`\s*\|(.*)$/gm)) rows.set(name, rest.match(/#\d+/)?.[0] ?? "");
  return rows;
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return SOURCE.test(entry.name) && !entry.name.endsWith(".d.ts") ? [path] : [];
  });
}

/** 이름마다 화면에서 나오는 곳(`파일:줄`). */
export function findUses(names: Iterable<string>, files: { path: string; text: string }[]): Map<string, string[]> {
  const uses = new Map<string, string[]>();
  for (const name of names) {
    const word = new RegExp(`\\b${name}\\b`);
    const where = files.flatMap(({ path, text }) =>
      text.split("\n").flatMap((line, i) => (word.test(line) ? [`${path}:${i + 1}`] : [])),
    );
    if (where.length) uses.set(name, where);
  }
  return uses;
}

/** 표와 실제가 다른 곳. 비어 있어야 한다. */
export function problems(deprecated: Map<string, string[]>, uses: Map<string, string[]>, known: Map<string, string>): string[] {
  const out: string[] = [];
  for (const [name, where] of uses) {
    if (!known.has(name)) {
      out.push(`${name}: 스펙에서 deprecated인데 화면이 쓴다 — 새 칸으로 옮기거나, 옮길 FE 이슈를 docs/openapi-workflow.md 「화면이 아직 쓰는 deprecated 필드」 표에 적는다\n    ${where.join("\n    ")}`);
    }
  }
  for (const [name, issue] of known) {
    if (!issue) out.push(`${name}: 표의 줄에 FE 이슈 번호(#N)가 없다`);
    if (!deprecated.has(name)) out.push(`${name}: 표에 있는데 스펙에서 deprecated가 아니다 — 표에서 지운다`);
    else if (!uses.has(name)) out.push(`${name}: 표에 있는데 화면이 더는 쓰지 않는다 — 표에서 지운다(${issue})`);
  }
  return out;
}

describe("스펙의 deprecated 필드와 화면", () => {
  it("화면이 쓰는 deprecated 필드는 모두 표에 FE 이슈와 함께 있고, 표의 줄은 실제와 같다", () => {
    const deprecated = collectDeprecated(load(readFileSync(SPEC, "utf8")));
    const files = sourceFiles(FRONTEND_SRC).map((path) => ({ path: relative(REPO, path).replaceAll("\\", "/"), text: readFileSync(path, "utf8") }));
    const found = problems(deprecated, findUses(deprecated.keys(), files), readKnownTable(readFileSync(WORKFLOW, "utf8")));
    expect(found, found.join("\n")).toEqual([]);
  });

  it("검사 자체: deprecated 속성·파라미터를 모으고, 표에 없는 사용과 낡은 표 줄을 잡는다", () => {
    const spec = {
      components: { schemas: { Run: { properties: { old_min: { type: "integer", deprecated: true }, new_m: { type: "integer" } } } } },
      paths: { "/runs": { get: { parameters: [{ name: "old_q", in: "query", deprecated: true }, { name: "q", in: "query" }] } } },
    };
    const deprecated = collectDeprecated(spec);
    expect([...deprecated.keys()].sort()).toEqual(["old_min", "old_q"]);

    const files = [{ path: "a.tsx", text: "const x = run.old_min\nconst y = run.new_m" }];
    const uses = findUses(deprecated.keys(), files);
    expect(uses).toEqual(new Map([["old_min", ["a.tsx:1"]]]));

    expect(problems(deprecated, uses, new Map())).toHaveLength(1);                       // 표에 없는 사용
    expect(problems(deprecated, uses, new Map([["old_min", "#1"]]))).toEqual([]);        // 표에 있으면 통과
    expect(problems(deprecated, new Map(), new Map([["old_min", "#1"]]))).toHaveLength(1); // 다 옮겼는데 표에 남음
    expect(problems(deprecated, uses, new Map([["old_min", ""]]))).toHaveLength(1);      // 이슈 번호 없음
    expect(readKnownTable(`${TABLE_HEADING}\n\n| 필드 | FE 이슈 |\n|---|---|\n| \`old_min\` | #12 화면 |\n\n## 다음`)).toEqual(new Map([["old_min", "#12"]]));
  });
});
