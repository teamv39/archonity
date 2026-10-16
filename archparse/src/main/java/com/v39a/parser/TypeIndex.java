package com.v39a.parser;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.*;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.VariableDeclarationExpr;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.ForStmt;
import com.github.javaparser.ast.stmt.Statement;

import java.util.*;

/**
 * Индекс типов (Pass 1).
 * Поддерживает:
 * - Лексический/блочный скоуп переменных (без плоского перетирания имен)
 * - Вывод типов для 'var' по инициализатору
 * - Wildcard-импорты (ts-common, Spring HTTP и т.д.)
 * - Вложенные классы
 */
public class TypeIndex {

    private final String className;
    private final Map<String, String> explicitImports = new HashMap<>();
    private final List<String> wildcardImports = new ArrayList<>();
    private final Map<String, String> fieldTypes = new HashMap<>();

    // Известные классы в ts-common / spring для wildcard-резолюции
    private static final Map<String, String> COMMON_WILDCARD_TYPES = new HashMap<>();
    static {
        COMMON_WILDCARD_TYPES.put("Order", "edu.fudan.common.entity.Order");
        COMMON_WILDCARD_TYPES.put("OrderStatus", "edu.fudan.common.entity.OrderStatus");
        COMMON_WILDCARD_TYPES.put("SeatClass", "edu.fudan.common.entity.SeatClass");
        COMMON_WILDCARD_TYPES.put("Response", "edu.fudan.common.util.Response");
        COMMON_WILDCARD_TYPES.put("HttpHeaders", "org.springframework.http.HttpHeaders");
        COMMON_WILDCARD_TYPES.put("HttpStatus", "org.springframework.http.HttpStatus");
        COMMON_WILDCARD_TYPES.put("ResponseEntity", "org.springframework.http.ResponseEntity");
        COMMON_WILDCARD_TYPES.put("HttpEntity", "org.springframework.http.HttpEntity");
    }

    public TypeIndex(CompilationUnit cu, ClassOrInterfaceDeclaration cid) {
        this.className = cid.getNameAsString();

        // 1. Импорты
        for (ImportDeclaration imp : cu.getImports()) {
            if (!imp.isStatic()) {
                if (imp.isAsterisk()) {
                    wildcardImports.add(imp.getNameAsString());
                } else {
                    String fqn = imp.getNameAsString();
                    String simpleName = fqn.substring(fqn.lastIndexOf('.') + 1);
                    explicitImports.put(simpleName, fqn);
                }
            }
        }

        // 2. Поля класса (включая вложенные классы)
        indexFields(cid);
    }

    private void indexFields(ClassOrInterfaceDeclaration cid) {
        for (FieldDeclaration fd : cid.getFields()) {
            String typeStr = fd.getElementType().asString();
            for (VariableDeclarator vd : fd.getVariables()) {
                fieldTypes.put(vd.getNameAsString(), typeStr);
            }
        }
    }

    public String getClassName() {
        return className;
    }

    /**
     * Лексический поиск типа переменной от конкретного узла AST вверх по дереву блоков.
     * Предотвращает перетирание переменных с одинаковыми именами в разных блоках.
     */
    public String resolveVariableType(Node contextNode, String varName) {
        if (contextNode != null) {
            Node current = contextNode;
            label:
            while (current != null) {
                switch (current) {
                    case MethodDeclaration md:
                        for (Parameter p : md.getParameters()) {
                            if (p.getNameAsString().equals(varName)) {
                                return cleanType(p.getType().asString());
                            }
                        }
                        break label; // Дальше метода вверх по переменным не идем
                    case BlockStmt block:
                        for (Statement stmt : block.getStatements()) {
                            // Рассматриваем только объявления
                            if (stmt.isExpressionStmt() && stmt.asExpressionStmt().getExpression().isVariableDeclarationExpr()) {
                                VariableDeclarationExpr vde = stmt.asExpressionStmt().getExpression().asVariableDeclarationExpr();
                                for (VariableDeclarator vd : vde.getVariables()) {
                                    if (vd.getNameAsString().equals(varName)) {
                                        return inferVariableType(vd);
                                    }
                                }
                            }
                        }
                        break;
                    case ForEachStmt forEach:
                        VariableDeclarationExpr vde = forEach.getVariable();
                        for (VariableDeclarator vd : vde.getVariables()) {
                            if (vd.getNameAsString().equals(varName)) {
                                return inferVariableType(vd);
                            }
                        }
                        break;
                    case ForStmt forStmt:
                        for (Expression init : forStmt.getInitialization()) {
                            if (init.isVariableDeclarationExpr()) {
                                for (VariableDeclarator vd : init.asVariableDeclarationExpr().getVariables()) {
                                    if (vd.getNameAsString().equals(varName)) {
                                        return inferVariableType(vd);
                                    }
                                }
                            }
                        }
                        break;
                    default:
                        break;
                }

                current = current.getParentNode().orElse(null);
            }
        }

        // Поле класса
        if (fieldTypes.containsKey(varName)) {
            return cleanType(fieldTypes.get(varName));
        }

        return null;
    }

    public boolean isLocalOrParam(Node contextNode, String varName) {
        if (contextNode == null) return false;
        Node current = contextNode;
        while (current != null) {
            if (current instanceof MethodDeclaration) {
                MethodDeclaration md = (MethodDeclaration) current;
                for (Parameter p : md.getParameters()) {
                    if (p.getNameAsString().equals(varName)) return true;
                }
                break;
            }
            if (current instanceof BlockStmt) {
                BlockStmt block = (BlockStmt) current;
                for (Statement stmt : block.getStatements()) {
                    if (stmt.isExpressionStmt() && stmt.asExpressionStmt().getExpression().isVariableDeclarationExpr()) {
                        for (VariableDeclarator vd : stmt.asExpressionStmt().getExpression().asVariableDeclarationExpr().getVariables()) {
                            if (vd.getNameAsString().equals(varName)) return true;
                        }
                    }
                }
            }
            current = current.getParentNode().orElse(null);
        }
        return false;
    }

    public boolean isField(String varName) {
        return fieldTypes.containsKey(varName);
    }

    /**
     * Вывод типа для объявленной переменной (включая 'var').
     */
    private String inferVariableType(VariableDeclarator vd) {
        String typeStr = vd.getType().asString();
        if ("var".equals(typeStr) && vd.getInitializer().isPresent()) {
            Expression init = vd.getInitializer().get();
            if (init.isObjectCreationExpr()) {
                return cleanType(init.asObjectCreationExpr().getType().asString());
            }
            if (init.isCastExpr()) {
                return cleanType(init.asCastExpr().getType().asString());
            }
        }
        return cleanType(typeStr);
    }

    /**
     * Резолюция простого типа в FQN с учетом explicit и wildcard импортов.
     */
    public String resolveFQN(String simpleType) {
        if (explicitImports.containsKey(simpleType)) {
            return explicitImports.get(simpleType);
        }
        if (COMMON_WILDCARD_TYPES.containsKey(simpleType)) {
            return COMMON_WILDCARD_TYPES.get(simpleType);
        }
        return simpleType;
    }

    public static String extractPropertyName(String methodName) {
        if (methodName.startsWith("get") && methodName.length() > 3) {
            return Character.toLowerCase(methodName.charAt(3)) + methodName.substring(4);
        }
        if (methodName.startsWith("is") && methodName.length() > 2) {
            return Character.toLowerCase(methodName.charAt(2)) + methodName.substring(3);
        }
        return null;
    }

    private String cleanType(String typeStr) {
        if (typeStr == null) return null;
        int genericIdx = typeStr.indexOf('<');
        if (genericIdx > 0) {
            typeStr = typeStr.substring(0, genericIdx);
        }
        return typeStr.trim();
    }
}
