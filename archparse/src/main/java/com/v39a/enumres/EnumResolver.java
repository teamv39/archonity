package com.v39a.enumres;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.v39a.model.EnumConstantIR;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/**
 * правило R7
 * Разрешает константы OrderStatus и SeatClass для вызовов getCode() / getNameByCode().
 */
public class EnumResolver {

    public static final String ORDER_STATUS_FQN = "edu.fudan.common.entity.OrderStatus";
    public static final String SEAT_CLASS_FQN = "edu.fudan.common.entity.SeatClass";

    private static final Set<String> ORDER_STATUS_CONSTANTS = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
            "NOTPAID", "PAID", "COLLECTED", "CHANGE", "CANCEL", "REFUNDS", "USED"
    )));

    private static final Set<String> SEAT_CLASS_CONSTANTS = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
            "NONE", "BUSINESS", "FIRSTCLASS", "SECONDCLASS", "HARDSEAT", "SOFTSEAT",
            "HARDBED", "SOFTBED", "HIGHSOFTBED"
    )));

    /**
     * Проверяет, является ли вызов метода вызовом на enum-константе.
     * Если да, возвращает EnumConstantIR, иначе null.
     */
    public static EnumConstantIR resolveCall(MethodCallExpr call, CompilationUnit cu) {
        if (!call.getScope().isPresent()) {
            return null;
        }

        Expression scope = call.getScope().get();
        return resolveExpression(scope, cu);
    }

    /**
     * Проверяет выражение на принадлежность к известной enum-константе.
     */
    public static EnumConstantIR resolveExpression(Expression expr, CompilationUnit cu) {
        if (expr == null) {
            return null;
        }

        if (expr.isFieldAccessExpr()) {
            FieldAccessExpr fae = expr.asFieldAccessExpr();
            String constName = fae.getNameAsString();
            String scopeStr = fae.getScope().toString();

            if (scopeStr.equals("OrderStatus") || scopeStr.endsWith(".OrderStatus")) {
                if (ORDER_STATUS_CONSTANTS.contains(constName)) {
                    return new EnumConstantIR(ORDER_STATUS_FQN, constName);
                }
            } else if (scopeStr.equals("SeatClass") || scopeStr.endsWith(".SeatClass")) {
                if (SEAT_CLASS_CONSTANTS.contains(constName)) {
                    return new EnumConstantIR(SEAT_CLASS_FQN, constName);
                }
            }
        } else if (expr.isNameExpr()) {
            String name = expr.asNameExpr().getNameAsString();
            if (ORDER_STATUS_CONSTANTS.contains(name) && hasStaticImport(cu, ORDER_STATUS_FQN, name)) {
                return new EnumConstantIR(ORDER_STATUS_FQN, name);
            }
            if (SEAT_CLASS_CONSTANTS.contains(name) && hasStaticImport(cu, SEAT_CLASS_FQN, name)) {
                return new EnumConstantIR(SEAT_CLASS_FQN, name);
            }
        }

        return null;
    }

    public static boolean isKnownEnumConstant(String type, String constant) {
        if (ORDER_STATUS_FQN.equals(type)) {
            return ORDER_STATUS_CONSTANTS.contains(constant);
        }
        if (SEAT_CLASS_FQN.equals(type)) {
            return SEAT_CLASS_CONSTANTS.contains(constant);
        }
        return false;
    }

    private static boolean hasStaticImport(CompilationUnit cu, String enumFqn, String constName) {
        if (cu == null) return false;
        for (ImportDeclaration imp : cu.getImports()) {
            if (imp.isStatic()) {
                String impName = imp.getNameAsString();
                if (imp.isAsterisk() && impName.equals(enumFqn)) {
                    return true;
                }
                if (impName.equals(enumFqn + "." + constName)) {
                    return true;
                }
            }
        }
        return false;
    }
}
