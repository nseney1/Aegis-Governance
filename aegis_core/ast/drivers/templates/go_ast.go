// Go Normalized AST Driver for Soma.
// Emits JSON conforming to Soma's NormalizedAST schema (v1.0).
// Zero third-party dependencies: uses standard library go/parser, go/token, go/ast.
package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"strings"
)

type DefinitionNode struct {
	Name       string  `json:"name"`
	Kind       string  `json:"kind"`
	Line       int     `json:"line"`
	Column     int     `json:"column"`
	EndLine    *int    `json:"end_line"`
	IsExported bool    `json:"is_exported"`
	IsMethod   bool    `json:"is_method"`
	ClassName  *string `json:"class_name"`
	Docstring  *string `json:"docstring"`
}

type CallSiteNode struct {
	Target      string  `json:"target"`
	Line        int     `json:"line"`
	Column      int     `json:"column"`
	CallerScope *string `json:"caller_scope"`
}

type ImportNode struct {
	Module        string   `json:"module"`
	ImportedNames []string `json:"imported_names"`
	Alias         *string  `json:"alias"`
	IsWildcard    bool     `json:"is_wildcard"`
	Line          int      `json:"line"`
}

type MutationPoint struct {
	Line          int     `json:"line"`
	Column        int     `json:"column"`
	Original      string  `json:"original"`
	Mutated       string  `json:"mutated"`
	Kind          string  `json:"kind"`
	FunctionScope *string `json:"function_scope"`
	ByteOffset    *int    `json:"byte_offset"`
}

type NormalizedAST struct {
	Version     string           `json:"version"`
	FilePath    string           `json:"file_path"`
	Language    string           `json:"language"`
	Definitions []DefinitionNode `json:"definitions"`
	CallSites   []CallSiteNode   `json:"call_sites"`
	Imports     []ImportNode     `json:"imports"`
	Mutations   []MutationPoint  `json:"mutations"`
}

func getReceiverTypeName(recv *ast.FieldList) *string {
	if recv == nil || len(recv.List) == 0 {
		return nil
	}
	t := recv.List[0].Type
	if star, ok := t.(*ast.StarExpr); ok {
		if ident, ok := star.X.(*ast.Ident); ok {
			s := ident.Name
			return &s
		}
	} else if ident, ok := t.(*ast.Ident); ok {
		s := ident.Name
		return &s
	}
	return nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: %s <file_path>\n", os.Args[0])
		os.Exit(1)
	}

	filePath := os.Args[1]
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, filePath, nil, parser.ParseComments)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Parse error: %v\n", err)
		os.Exit(1)
	}

	norm := NormalizedAST{
		Version:     "1.0",
		FilePath:    filePath,
		Language:    "go",
		Definitions: make([]DefinitionNode, 0),
		CallSites:   make([]CallSiteNode, 0),
		Imports:     make([]ImportNode, 0),
		Mutations:   make([]MutationPoint, 0),
	}

	// 1. Extract Imports
	for _, imp := range file.Imports {
		pos := fset.Position(imp.Pos())
		mod := strings.Trim(imp.Path.Value, "\"")
		var alias *string
		isWildcard := false
		if imp.Name != nil {
			a := imp.Name.Name
			alias = &a
			if a == "." {
				isWildcard = true
			}
		}
		norm.Imports = append(norm.Imports, ImportNode{
			Module:        mod,
			ImportedNames: []string{},
			Alias:         alias,
			IsWildcard:    isWildcard,
			Line:          pos.Line,
		})
	}

	binopSwaps := map[token.Token]struct {
		mut  string
		kind string
	}{
		token.EQL:  {"!=", "cmpop"},
		token.NEQ:  {"==", "cmpop"},
		token.LSS:  {">", "cmpop"},
		token.GTR:  {"<", "cmpop"},
		token.LEQ:  {">=", "cmpop"},
		token.GEQ:  {"<=", "cmpop"},
		token.LAND: {"||", "boolop"},
		token.LOR:  {"&&", "boolop"},
		token.ADD:  {"-", "binop"},
		token.SUB:  {"+", "binop"},
		token.MUL:  {"/", "binop"},
		token.QUO:  {"*", "binop"},
	}

	// 2. Extract Declarations
	for _, decl := range file.Decls {
		switch d := decl.(type) {
		case *ast.GenDecl:
			if d.Tok == token.TYPE {
				for _, spec := range d.Specs {
					if ts, ok := spec.(*ast.TypeSpec); ok {
						pos := fset.Position(ts.Pos())
						isExp := ts.Name.IsExported()
						var doc *string
						if ts.Doc != nil {
							t := ts.Doc.Text()
							doc = &t
						}
						norm.Definitions = append(norm.Definitions, DefinitionNode{
							Name:       ts.Name.Name,
							Kind:       "type",
							Line:       pos.Line,
							Column:     pos.Column - 1,
							IsExported: isExp,
							IsMethod:   false,
							ClassName:  nil,
							Docstring:  doc,
						})
					}
				}
			}
		case *ast.FuncDecl:
			pos := fset.Position(d.Pos())
			endPos := fset.Position(d.End())
			endLine := endPos.Line
			isExp := d.Name.IsExported()
			isMethod := d.Recv != nil
			kind := "function"
			if isMethod {
				kind = "method"
			}
			className := getReceiverTypeName(d.Recv)
			var doc *string
			if d.Doc != nil {
				t := d.Doc.Text()
				doc = &t
			}

			norm.Definitions = append(norm.Definitions, DefinitionNode{
				Name:       d.Name.Name,
				Kind:       kind,
				Line:       pos.Line,
				Column:     pos.Column - 1,
				EndLine:    &endLine,
				IsExported: isExp,
				IsMethod:   isMethod,
				ClassName:  className,
				Docstring:  doc,
			})

			funcName := d.Name.Name

			// Traverse function body for calls and mutations
			if d.Body != nil {
				ast.Inspect(d.Body, func(n ast.Node) bool {
					if n == nil {
						return true
					}

					// Calls
					if call, ok := n.(*ast.CallExpr); ok {
						callPos := fset.Position(call.Pos())
						var target string
						if ident, ok := call.Fun.(*ast.Ident); ok {
							target = ident.Name
						} else if sel, ok := call.Fun.(*ast.SelectorExpr); ok {
							target = sel.Sel.Name
						}
						if target != "" {
							scope := funcName
							norm.CallSites = append(norm.CallSites, CallSiteNode{
								Target:      target,
								Line:        callPos.Line,
								Column:      callPos.Column - 1,
								CallerScope: &scope,
							})
						}
					}

					// Mutations
					if binExpr, ok := n.(*ast.BinaryExpr); ok {
						if swapInfo, exists := binopSwaps[binExpr.Op]; exists {
							opPos := fset.Position(binExpr.OpPos)
							scope := funcName
							offset := opPos.Offset
							norm.Mutations = append(norm.Mutations, MutationPoint{
								Line:          opPos.Line,
								Column:        opPos.Column - 1,
								Original:      binExpr.Op.String(),
								Mutated:       swapInfo.mut,
								Kind:          swapInfo.kind,
								FunctionScope: &scope,
								ByteOffset:    &offset,
							})
						}
					}

					return true
				})
			}
		}
	}

	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(norm); err != nil {
		fmt.Fprintf(os.Stderr, "JSON encoding error: %v\n", err)
		os.Exit(1)
	}
}
