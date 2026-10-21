package com.v39a.parser;

import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.stmt.*;

import java.util.List;
import java.util.Optional;

/**
 * Чего ждёт успешный путь метода от результата чтения репозитория.
 *
 * Результат проверяется условием (== null, isPresent(), isEmpty(), size()). Если плечо «строка найдена»
 * всегда заканчивается ошибкой, а плечо «не найдена» нет, успешный путь ждёт пустой результат (EMPTY):
 * так устроены проверки «уже существует» перед созданием. Обратный случай даёт ROWS.
 * Ошибка плеча: throw, return new Response<>(0, ...) или LOGGER.error/warn перед return.
 * Всё остальное — UNKNOWN, тогда решает состояние БД на стороне движка.
 */
final class ResultExpectation {

    static final String ROWS = "ROWS";
    static final String EMPTY = "EMPTY";
    static final String UNKNOWN = "UNKNOWN";

    /** Полярность проверки: истинна, когда строка найдена (FOUND), или когда не найдена (ABSENT). */
    private enum Polarity { FOUND, ABSENT, MIXED }

    private ResultExpectation() {}

    /** Возвращает {expects, reason}. */
    static String[] analyze(MethodCallExpr call) {
        Node parent = call.getParentNode().orElse(null);
        Expression result = call;

        // Цепочка на Optional: orElseThrow()/get() требуют строку, orElse(null) даёт обычную nullable-переменную
        while (parent instanceof MethodCallExpr chained && chained.getScope().orElse(null) == result) {
            String name = chained.getNameAsString();
            if (name.equals("orElseThrow") || name.equals("get")) {
                return new String[]{ROWS, "line " + EntityScanner.line(chained) + ": ." + name + "()"};
            }
            if (name.equals("isPresent") || name.equals("isEmpty")) {
                break;
            }
            if (!name.equals("orElse")) {
                return new String[]{UNKNOWN, "chained ." + name + "()"};
            }
            result = chained;
            parent = chained.getParentNode().orElse(null);
        }

        // Проверка прямо в условии: if (repo.find(x) == null), if (repo.find(x).isPresent())
        IfStmt direct = enclosingIfCondition(result);
        if (direct != null) {
            Polarity p = polarity(direct.getCondition(), result, null);
            return decide(direct, p);
        }

        String var = assignedVariable(result);
        if (var == null) {
            return new String[]{UNKNOWN, "result not checked"};
        }

        // Первое условие после вызова, проверяющее переменную
        Node body = EntityScanner.enclosingBody(call);
        IfStmt test = null;
        for (IfStmt s : body.findAll(IfStmt.class)) {
            if (EntityScanner.before(call, s) && polarity(s.getCondition(), null, var) != null) {
                if (test == null || EntityScanner.before(s, test)) {
                    test = s;
                }
            }
        }
        if (test == null) {
            return new String[]{UNKNOWN, "variable " + var + " not checked"};
        }
        return decide(test, polarity(test.getCondition(), null, var));
    }

    private static String[] decide(IfStmt test, Polarity p) {
        String where = "line " + EntityScanner.line(test) + ": if (" + test.getCondition() + ")";
        if (p == null || p == Polarity.MIXED) {
            return new String[]{UNKNOWN, where + ": mixed condition"};
        }
        boolean thenErr = armError(test.getThenStmt());
        boolean elseErr;
        if (test.getElseStmt().isPresent()) {
            elseErr = armError(test.getElseStmt().get());
        } else if (endsAbruptly(test.getThenStmt())) {
            elseErr = listError(followingStatements(test));
        } else {
            elseErr = false;
        }
        boolean foundErr = p == Polarity.FOUND ? thenErr : elseErr;
        boolean absentErr = p == Polarity.FOUND ? elseErr : thenErr;
        if (foundErr && !absentErr) {
            return new String[]{EMPTY, where + ": found arm fails"};
        }
        if (absentErr && !foundErr) {
            return new String[]{ROWS, where + ": absent arm fails"};
        }
        return new String[]{UNKNOWN, where + ": no failing arm"};
    }

    /**
     * Полярность условия относительно результата. Проверяемое — либо само выражение вызова (expr),
     * либо переменная (var). null — условие результат не проверяет.
     */
    private static Polarity polarity(Expression cond, Expression expr, String var) {
        if (cond instanceof EnclosedExpr e) {
            return polarity(e.getInner(), expr, var);
        }
        if (cond instanceof UnaryExpr u && u.getOperator() == UnaryExpr.Operator.LOGICAL_COMPLEMENT) {
            Polarity p = polarity(u.getExpression(), expr, var);
            if (p == Polarity.FOUND) return Polarity.ABSENT;
            if (p == Polarity.ABSENT) return Polarity.FOUND;
            return p;
        }
        if (cond instanceof BinaryExpr b) {
            BinaryExpr.Operator op = b.getOperator();
            if (op == BinaryExpr.Operator.OR || op == BinaryExpr.Operator.AND) {
                Polarity l = polarity(b.getLeft(), expr, var);
                Polarity r = polarity(b.getRight(), expr, var);
                if (l == null && r == null) return null;
                // Все листья должны проверять результат и иметь одну полярность
                if (l == null || r == null || l != r) return Polarity.MIXED;
                return l;
            }
            Expression other = null;
            if (isSubject(b.getLeft(), expr, var)) other = b.getRight();
            else if (isSubject(b.getRight(), expr, var)) other = b.getLeft();
            if (other instanceof NullLiteralExpr) {
                if (op == BinaryExpr.Operator.EQUALS) return Polarity.ABSENT;
                if (op == BinaryExpr.Operator.NOT_EQUALS) return Polarity.FOUND;
            }
            // x.size() == 0, x.size() > 0, x.size() != 0
            Expression sizeSide = sizeCallOn(b.getLeft(), expr, var) ? b.getLeft() : null;
            if (sizeSide != null && b.getRight() instanceof IntegerLiteralExpr lit && lit.asNumber().intValue() == 0) {
                if (op == BinaryExpr.Operator.EQUALS || op == BinaryExpr.Operator.LESS_EQUALS) return Polarity.ABSENT;
                if (op == BinaryExpr.Operator.GREATER || op == BinaryExpr.Operator.NOT_EQUALS) return Polarity.FOUND;
            }
            return null;
        }
        if (cond instanceof MethodCallExpr mc && mc.getScope().isPresent() && isSubject(mc.getScope().get(), expr, var)) {
            if (mc.getNameAsString().equals("isPresent")) return Polarity.FOUND;
            if (mc.getNameAsString().equals("isEmpty")) return Polarity.ABSENT;
        }
        return null;
    }

    private static boolean isSubject(Expression e, Expression expr, String var) {
        if (e instanceof EnclosedExpr en) return isSubject(en.getInner(), expr, var);
        if (expr != null) return e == expr;
        return e instanceof NameExpr n && n.getNameAsString().equals(var);
    }

    private static boolean sizeCallOn(Expression e, Expression expr, String var) {
        return e instanceof MethodCallExpr mc && mc.getNameAsString().equals("size")
                && mc.getScope().isPresent() && isSubject(mc.getScope().get(), expr, var);
    }

    /** if, в условии которого стоит выражение (через бинарные/логические операторы и вызовы isPresent). */
    private static IfStmt enclosingIfCondition(Expression e) {
        Node cur = e;
        Node parent = e.getParentNode().orElse(null);
        while (parent instanceof Expression) {
            cur = parent;
            parent = parent.getParentNode().orElse(null);
        }
        if (parent instanceof IfStmt s && s.getCondition() == cur) {
            return s;
        }
        return null;
    }

    private static String assignedVariable(Expression e) {
        Node parent = e.getParentNode().orElse(null);
        if (parent instanceof CastExpr || parent instanceof EnclosedExpr) {
            return assignedVariable((Expression) parent);
        }
        if (parent instanceof VariableDeclarator vd) {
            return vd.getNameAsString();
        }
        if (parent instanceof AssignExpr a && a.getTarget() instanceof NameExpr n) {
            return n.getNameAsString();
        }
        return null;
    }

    // ------------------------------------------------------------------
    // Плечо с ошибкой
    // ------------------------------------------------------------------

    static boolean armError(Statement s) {
        if (s instanceof BlockStmt b) return listError(b.getStatements());
        if (s instanceof IfStmt i) {
            return i.getElseStmt().isPresent() && armError(i.getThenStmt()) && armError(i.getElseStmt().get());
        }
        return listError(List.of(s));
    }

    /**
     * Последовательность операторов — путь отказа: throw, return new Response<>(0, ...) или LOGGER.error/warn
     * на верхнем уровне. Лог ошибки считается отказом и при return new Response<>(1, ...) («Trip already exists»)
     * и без return. Допущение о соглашении проекта: путь отказа пишет error/warn (так во всех сервисах Train Ticket).
     */
    static boolean listError(List<Statement> stmts) {
        for (Statement s : stmts) {
            if (s instanceof ThrowStmt) return true;
            if (s instanceof ExpressionStmt es && es.getExpression() instanceof MethodCallExpr mc && isErrorLog(mc)) {
                return true;
            }
            if (s instanceof ReturnStmt r) {
                return isErrorReturn(r);
            }
            if (s instanceof IfStmt i && i.getElseStmt().isPresent()
                    && endsAbruptly(i.getThenStmt()) && endsAbruptly(i.getElseStmt().get())) {
                return armError(i);
            }
        }
        return false;
    }

    private static boolean isErrorLog(MethodCallExpr mc) {
        String name = mc.getNameAsString();
        return (name.equals("error") || name.equals("warn"))
                && mc.getScope().map(sc -> sc.toString().toLowerCase().contains("log")).orElse(false);
    }

    private static Optional<Integer> responseStatus(ReturnStmt r) {
        if (r.getExpression().isPresent() && r.getExpression().get() instanceof ObjectCreationExpr oce
                && oce.getType().getNameAsString().equals("Response") && !oce.getArguments().isEmpty()
                && oce.getArgument(0) instanceof IntegerLiteralExpr lit) {
            return Optional.of(lit.asNumber().intValue());
        }
        return Optional.empty();
    }

    private static boolean isErrorReturn(ReturnStmt r) {
        return responseStatus(r).map(v -> v == 0).orElse(false);
    }

    static boolean endsAbruptly(Statement s) {
        if (s instanceof ReturnStmt || s instanceof ThrowStmt) return true;
        if (s instanceof BlockStmt b) {
            for (Statement x : b.getStatements()) {
                if (endsAbruptly(x)) return true;
            }
            return false;
        }
        if (s instanceof IfStmt i) {
            return i.getElseStmt().isPresent() && endsAbruptly(i.getThenStmt()) && endsAbruptly(i.getElseStmt().get());
        }
        return false;
    }

    /** Операторы блока, идущие после данного if (продолжение пути, когда then-плечо вышло из метода). */
    private static List<Statement> followingStatements(IfStmt s) {
        Node parent = s.getParentNode().orElse(null);
        if (parent instanceof BlockStmt b) {
            List<Statement> all = b.getStatements();
            for (int i = 0; i < all.size(); i++) {
                if (all.get(i) == s) {
                    return all.subList(i + 1, all.size());
                }
            }
        }
        return List.of();
    }
}
