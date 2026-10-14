#!/usr/bin/env node
/**
 * TypeScript & JavaScript Normalized AST Driver for Soma.
 * Emits JSON conforming to Soma's NormalizedAST schema (v1.0).
 *
 * Uses the official 'typescript' compiler API when available,
 * and falls back to a deterministic zero-dependency lexer/parser
 * when run in environments without node_modules.
 */
"use strict";

const fs = require("fs");
const path = require("path");

function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.error("Usage: ts_ast.js <file_path>");
    process.exit(1);
  }

  const filePath = args[0];
  if (!fs.existsSync(filePath)) {
    console.error(`File not found: ${filePath}`);
    process.exit(1);
  }

  const source = fs.readFileSync(filePath, "utf-8");
  const ext = path.extname(filePath).toLowerCase();
  const language = (ext === ".ts" || ext === ".tsx") ? "typescript" : "javascript";

  let ts = null;
  try {
    ts = require("typescript");
  } catch (e1) {
    try {
      ts = require(path.join(process.cwd(), "node_modules", "typescript"));
    } catch (e2) {
      ts = null;
    }
  }

  let result;
  if (ts) {
    result = parseWithTypeScriptCompiler(ts, filePath, source, language);
  } else {
    result = parseWithBuiltinLexer(filePath, source, language);
  }

  const output = JSON.stringify(result, null, 2) + "\n";
  if (!process.stdout.write(output)) {
    process.stdout.once("drain", () => process.exit(0));
  } else {
    process.exit(0);
  }
}

/**
 * Robust compiler-backed parser using official typescript module.
 */
function parseWithTypeScriptCompiler(ts, filePath, source, language) {
  const sourceFile = ts.createSourceFile(
    filePath,
    source,
    ts.ScriptTarget.Latest,
    /*setParentNodes*/ true
  );

  const definitions = [];
  const callSites = [];
  const imports = [];
  const mutations = [];

  const BINOP_SWAPS = {
    [ts.SyntaxKind.EqualsEqualsEqualsToken]: "!==",
    [ts.SyntaxKind.ExclamationEqualsEqualsToken]: "===",
    [ts.SyntaxKind.EqualsEqualsToken]: "!=",
    [ts.SyntaxKind.ExclamationEqualsToken]: "==",
    [ts.SyntaxKind.LessThanToken]: ">",
    [ts.SyntaxKind.GreaterThanToken]: "<",
    [ts.SyntaxKind.LessThanEqualsToken]: ">=",
    [ts.SyntaxKind.GreaterThanEqualsToken]: "<=",
    [ts.SyntaxKind.AmpersandAmpersandToken]: "||",
    [ts.SyntaxKind.BarBarToken]: "&&",
    [ts.SyntaxKind.PlusToken]: "-",
    [ts.SyntaxKind.MinusToken]: "+",
    [ts.SyntaxKind.AsteriskToken]: "/",
    [ts.SyntaxKind.SlashToken]: "*",
  };

  let currentScope = null;

  function visit(node) {
    const prevScope = currentScope;

    // 1. Imports
    if (ts.isImportDeclaration(node)) {
      const moduleName = node.moduleSpecifier ? node.moduleSpecifier.text : "";
      const names = [];
      let isWildcard = false;
      let alias = null;

      if (node.importClause) {
        if (node.importClause.name) {
          names.push(node.importClause.name.text);
        }
        if (node.importClause.namedBindings) {
          if (ts.isNamespaceImport(node.importClause.namedBindings)) {
            isWildcard = true;
            alias = node.importClause.namedBindings.name.text;
          } else if (ts.isNamedImports(node.importClause.namedBindings)) {
            for (const elem of node.importClause.namedBindings.elements) {
              names.push(elem.name.text);
            }
          }
        }
      }

      const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
      imports.push({
        source: moduleName,
        imported_symbols: names,
        module: moduleName,
        imported_names: names,
        alias: alias,
        is_wildcard: isWildcard,
        line: line + 1,
      });
    }

    // 2. Definitions
    if (ts.isFunctionDeclaration(node) && node.name) {
      const isExported = Boolean(
        node.modifiers && node.modifiers.some(m => m.kind === ts.SyntaxKind.ExportKeyword)
      );
      const start = sourceFile.getLineAndCharacterOfPosition(node.getStart());
      const end = sourceFile.getLineAndCharacterOfPosition(node.getEnd());
      definitions.push({
        name: node.name.text,
        kind: "function",
        line: start.line + 1,
        column: start.character,
        end_line: end.line + 1,
        is_exported: isExported,
        is_method: false,
        class_name: null,
        docstring: null,
      });
      currentScope = node.name.text;
    } else if (ts.isClassDeclaration(node) && node.name) {
      const isExported = Boolean(
        node.modifiers && node.modifiers.some(m => m.kind === ts.SyntaxKind.ExportKeyword)
      );
      const start = sourceFile.getLineAndCharacterOfPosition(node.getStart());
      definitions.push({
        name: node.name.text,
        kind: "class",
        line: start.line + 1,
        column: start.character,
        end_line: null,
        is_exported: isExported,
        is_method: false,
        class_name: null,
        docstring: null,
      });
      currentScope = node.name.text;
    } else if (ts.isMethodDeclaration(node) && node.name) {
      const start = sourceFile.getLineAndCharacterOfPosition(node.getStart());
      const className = node.parent && node.parent.name ? node.parent.name.text : null;
      definitions.push({
        name: node.name.text,
        kind: "method",
        line: start.line + 1,
        column: start.character,
        end_line: null,
        is_exported: false,
        is_method: true,
        class_name: className,
        docstring: null,
      });
      currentScope = node.name.text;
    }

    // 3. Call sites
    if (ts.isCallExpression(node)) {
      let target = "";
      if (ts.isIdentifier(node.expression)) {
        target = node.expression.text;
      } else if (ts.isPropertyAccessExpression(node.expression)) {
        target = node.expression.name.text;
      } else {
        target = node.expression.getText(sourceFile);
      }
      const start = sourceFile.getLineAndCharacterOfPosition(node.getStart());
      callSites.push({
        target: target,
        line: start.line + 1,
        column: start.character,
        caller_scope: currentScope,
      });
    }

    // 4. Mutation points (Binary expressions)
    if (ts.isBinaryExpression(node)) {
      const opToken = node.operatorToken;
      const swap = BINOP_SWAPS[opToken.kind];
      if (swap) {
        const opPos = sourceFile.getLineAndCharacterOfPosition(opToken.getStart());
        mutations.push({
          line: opPos.line + 1,
          col: opPos.character,
          column: opPos.character,
          original_op: opToken.getText(sourceFile),
          replacement_op: swap,
          original: opToken.getText(sourceFile),
          mutated: swap,
          mutation_type: "binop",
          kind: "binop",
          function_scope: currentScope,
          byte_offset: opToken.getStart(),
        });
      }
    }

    ts.forEachChild(node, visit);
    currentScope = prevScope;
  }

  visit(sourceFile);

  return {
    version: "1.0",
    file_path: filePath,
    language: language,
    definitions: definitions,
    call_sites: callSites,
    imports: imports,
    mutation_points: mutations,
    mutations: mutations,
  };
}

/**
 * Built-in zero-dependency fallback lexer/parser for Node.js environments.
 */
function parseWithBuiltinLexer(filePath, source, language) {
  const definitions = [];
  const callSites = [];
  const imports = [];
  const mutations = [];

  const lines = source.split(/\r?\n/);

  // Strip comments & strings for clean symbol scanning
  const strippedSource = source.replace(/(".*?"|'.*?'|`.*?`|\/\*[\s\S]*?\*\/|\/\/.*)/g, (match) => {
    // Preserve newlines to keep line numbers aligned
    return match.replace(/[^\r\n]/g, " ");
  });
  const strippedLines = strippedSource.split(/\r?\n/);

  let byteOffset = 0;
  let currentClass = null;

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const stripped = strippedLines[i];
    const lineNum = i + 1;

    // 1. Imports
    // e.g., import { foo, bar } from 'module';
    // e.g., import * as lib from 'module';
    // e.g., import defaultExport from 'module';
    const importMatch = rawLine.match(/^\s*import\s+(?:(\*\s+as\s+(\w+))|\{([^}]+)\}|(\w+))\s+from\s+['"]([^'"]+)['"]/);
    if (importMatch) {
      let isWildcard = false;
      let alias = null;
      let names = [];
      const moduleName = importMatch[5];

      if (importMatch[1]) {
        isWildcard = true;
        alias = importMatch[2];
      } else if (importMatch[3]) {
        names = importMatch[3].split(",").map(s => s.trim().split(/\s+as\s+/)[0]).filter(Boolean);
      } else if (importMatch[4]) {
        names = [importMatch[4]];
      }

      imports.push({
        source: moduleName,
        imported_symbols: names,
        module: moduleName,
        imported_names: names,
        alias: alias,
        is_wildcard: isWildcard,
        line: lineNum,
      });
    }

    // 2. Class Definitions
    const classMatch = stripped.match(/(?:export\s+)?class\s+([a-zA-Z0-9_$]+)/);
    if (classMatch) {
      currentClass = classMatch[1];
      const isExported = rawLine.includes("export ");
      definitions.push({
        name: currentClass,
        kind: "class",
        line: lineNum,
        column: rawLine.indexOf(currentClass),
        end_line: null,
        is_exported: isExported,
        is_method: false,
        class_name: null,
        docstring: null,
      });
    }

    // 3. Function Definitions
    const funcMatch = stripped.match(/(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(/);
    const constFuncMatch = stripped.match(/(?:export\s+)?const\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>/);
    const matchedFunc = funcMatch || constFuncMatch;

    if (matchedFunc) {
      const funcName = matchedFunc[1];
      const isExported = rawLine.includes("export ");
      definitions.push({
        name: funcName,
        kind: "function",
        line: lineNum,
        column: rawLine.indexOf(funcName),
        end_line: null,
        is_exported: isExported,
        is_method: false,
        class_name: null,
        docstring: null,
      });
    }

    // 4. Method Definitions inside class
    if (currentClass) {
      const methodMatch = stripped.match(/^\s*(?:async\s+)?([a-zA-Z0-9_$]+)\s*\([^)]*\)\s*\{/);
      if (methodMatch && !["if", "for", "while", "switch", "catch"].includes(methodMatch[1])) {
        definitions.push({
          name: methodMatch[1],
          kind: "method",
          line: lineNum,
          column: rawLine.indexOf(methodMatch[1]),
          end_line: null,
          is_exported: false,
          is_method: true,
          class_name: currentClass,
          docstring: null,
        });
      }
    }

    // 5. Call Sites (heuristic: identifier followed by '(' not keyword)
    const callRegex = /\b([a-zA-Z0-9_$]+)\s*\(/g;
    let callMatch;
    const reserved = new Set(["function", "if", "for", "while", "switch", "catch", "return", "import", "class"]);
    while ((callMatch = callRegex.exec(stripped)) !== null) {
      const callee = callMatch[1];
      if (!reserved.has(callee)) {
        callSites.push({
          target: callee,
          line: lineNum,
          column: callMatch.index,
          caller_scope: null,
        });
      }
    }

    // 6. Mutation Points (Binary and comparison operators)
    const MUT_OPS = [
      { op: "===", swap: "!==" },
      { op: "!==", swap: "===" },
      { op: "==", swap: "!=" },
      { op: "!=", swap: "==" },
      { op: "<=", swap: ">=" },
      { op: ">=", swap: "<=" },
      { op: "&&", swap: "||" },
      { op: "||", swap: "&&" },
    ];

    for (const item of MUT_OPS) {
      let idx = 0;
      while ((idx = stripped.indexOf(item.op, idx)) !== -1) {
        const mType = item.op.includes("=") || item.op.includes("<") || item.op.includes(">") ? "cmpop" : "boolop";
        mutations.push({
          line: lineNum,
          col: idx,
          column: idx,
          original_op: item.op,
          replacement_op: item.swap,
          original: item.op,
          mutated: item.swap,
          mutation_type: mType,
          kind: mType,
          function_scope: null,
          byte_offset: byteOffset + idx,
        });
        idx += item.op.length;
      }
    }

    byteOffset += rawLine.length + 1; // account for newline
  }

  return {
    version: "1.0",
    file_path: filePath,
    language: language,
    definitions: definitions,
    call_sites: callSites,
    imports: imports,
    mutation_points: mutations,
    mutations: mutations,
  };
}

if (require.main === module) {
  main();
}
