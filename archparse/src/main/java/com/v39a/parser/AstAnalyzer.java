package com.v39a.parser;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.stmt.*;
import com.v39a.config.TargetMethod;
import com.v39a.enumres.EnumResolver;
import com.v39a.model.BranchIR;
import com.v39a.model.CallIR;
import com.v39a.model.EnumConstantIR;
import com.v39a.model.MethodIR;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

public class AstAnalyzer {

    public static MethodIR analyze(TargetMethod target, MethodDeclaration md, CompilationUnit cu, TypeIndex typeIndex) {
        MethodIR methodIR = new MethodIR(target.methodId(), target.relativeFile());

        if (md.getBody().isEmpty()) {
            return methodIR;
        }

        BlockStmt body = md.getBody().get();

        // 1. Собираем известные имена методов текущего класса для точного определения SAME_CLASS
        Set<String> classMethodNames = new HashSet<>();
        md.findAncestor(ClassOrInterfaceDeclaration.class).ifPresent(cid -> {
            for (MethodDeclaration m : cid.getMethods()) {
                classMethodNames.add(m.getNameAsString());
            }
        });

        // 2. Извлекаем все вызовы с расчетом guard, kind, arg_count
        List<CallIR> calls = new ArrayList<>();
        extractCallsWithGuard(body, new ArrayList<>(), target.relativeFile(), cu, typeIndex, classMethodNames, calls);

        // Сортируем вызовы по строке, затем по колонке
        calls.sort(Comparator.comparingInt(CallIR::getLine).thenComparingInt(CallIR::getCol));
        methodIR.setCalls(calls);

        // 3. Извлекаем ветвления (branches) без дублирования вложенных вызовов
        List<BranchIR> branches = new ArrayList<>();
        body.walk(node -> {
            if (node instanceof IfStmt ifStmt) {
                if (isElseIfChild(ifStmt) || isInsideAnonymousClass(ifStmt)) {
                    return;
                }
                processIfChain(ifStmt, cu, typeIndex, branches);
            }
        });
        methodIR.setBranches(branches);

        // 4. Честно фиксируем неподдерживаемые конструкции (unsupported)
        List<String> unsupported = new ArrayList<>();
        body.walk(node -> {
            if (isInsideAnonymousClass(node)) {
                return;
            }
            if (node instanceof WhileStmt) {
                int line = node.getBegin().map(p -> p.line).orElse(0);
                unsupported.add("line " + line + ": while loop not modeled (R17)");
            } else if (node instanceof ForStmt) {
                int line = node.getBegin().map(p -> p.line).orElse(0);
                unsupported.add("line " + line + ": for loop not modeled (R17)");
            } else if (node instanceof ForEachStmt forEach) {
                int line = node.getBegin().map(p -> p.line).orElse(0);
                unsupported.add("line " + line + ": foreach body guarded as " + loopId(forEach) + " (assumed non-empty unless state says otherwise)");
            } else if (node instanceof ConditionalExpr) {
                int line = node.getBegin().map(p -> p.line).orElse(0);
                unsupported.add("line " + line + ": ternary operator not modeled");
            } else if (node instanceof SwitchStmt) {
                int line = node.getBegin().map(p -> p.line).orElse(0);
                unsupported.add("line " + line + ": switch statement not modeled");
            } else if (node instanceof LambdaExpr lambda) {
                int line = node.getBegin().map(p -> p.line).orElse(0);
                unsupported.add("line " + line + ": lambda body guarded as " + lambdaId(lambda) + " (executed only if the host invokes it)");
            } else if (node instanceof MethodReferenceExpr) {
                int line = node.getBegin().map(p -> p.line).orElse(0);
                unsupported.add("line " + line + ": method reference not modeled");
            }
        });
        methodIR.setUnsupported(unsupported);

        return methodIR;
    }

    /**
     * Рекурсивно обходит операторы метода, поддерживая стек текущих условий (guard) для каждого вызова.
     * Не заходит внутрь методов анонимных классов (R1).
     */
    private static void extractCallsWithGuard(
            Node node,
            List<String> currentGuard,
            String relFile,
            CompilationUnit cu,
            TypeIndex typeIndex,
            Set<String> classMethodNames,
            List<CallIR> resultCalls
    ) {
        if (node == null) return;

        // Если это вызов метода
        if (node instanceof MethodCallExpr call) {
            int line = call.getName().getBegin().map(p -> p.line).orElse(0);
            int col = skeletonCol(call.getName());
            String callee = call.getNameAsString();
            String receiver = call.getScope().map(Expression::toString).orElse("this");
            EnumConstantIR enumConst = EnumResolver.resolveCall(call, cu);
            int argCount = call.getArguments().size();

            String kind;
            if (enumConst != null) {
                kind = "ENUM";
            } else if ("this".equals(receiver) || (!call.getScope().isPresent() && classMethodNames.contains(callee))) {
                kind = "SAME_CLASS";
            } else {
                kind = "OTHER";
            }

            resultCalls.add(new CallIR(
                    relFile, line, col, callee, receiver, kind, argCount, new ArrayList<>(currentGuard), enumConst
            ));

            // Обходим аргументы и scope вызова (без изменения guard)
            if (call.getScope().isPresent()) {
                extractCallsWithGuard(call.getScope().get(), currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            }
            for (Expression arg : call.getArguments()) {
                extractCallsWithGuard(arg, currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            }
            return;
        }

        // Если это создание объекта new Foo(...)
        if (node instanceof ObjectCreationExpr creation) {
            int line = creation.getBegin().map(p -> p.line).orElse(0);
            int col = skeletonCol(creation);
            String callee = "<init>";
            String receiver = creation.getType().asString();
            int argCount = creation.getArguments().size();

            resultCalls.add(new CallIR(
                    relFile, line, col, callee, receiver, "CONSTRUCTOR", argCount, new ArrayList<>(currentGuard), null
            ));

            // Обходим аргументы создания объекта
            for (Expression arg : creation.getArguments()) {
                extractCallsWithGuard(arg, currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            }

            // По R1: НЕ обходим методы анонимного класса, если он есть
            return;
        }

        // try/catch: тело и finally идут при текущем guard, catch-плечи только при исключении (R15)
        if (node instanceof TryStmt tryStmt) {
            for (Expression resource : tryStmt.getResources()) {
                extractCallsWithGuard(resource, currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            }
            extractCallsWithGuard(tryStmt.getTryBlock(), currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            for (CatchClause cc : tryStmt.getCatchClauses()) {
                List<String> catchGuard = new ArrayList<>(currentGuard);
                catchGuard.add(tryId(tryStmt) + ":catch");
                extractCallsWithGuard(cc.getBody(), catchGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            }
            if (tryStmt.getFinallyBlock().isPresent()) {
                extractCallsWithGuard(tryStmt.getFinallyBlock().get(), currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            }
            return;
        }

        // foreach: тело исполняется, только если коллекция непуста (R17)
        if (node instanceof ForEachStmt forEach) {
            extractCallsWithGuard(forEach.getIterable(), currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            List<String> loopGuard = new ArrayList<>(currentGuard);
            loopGuard.add(loopId(forEach));
            extractCallsWithGuard(forEach.getBody(), loopGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            return;
        }

        // Лямбда: тело исполняется только если хост-метод её вызывает (R16)
        if (node instanceof LambdaExpr lambda) {
            List<String> lambdaGuard = new ArrayList<>(currentGuard);
            lambdaGuard.add(lambdaId(lambda));
            extractCallsWithGuard(lambda.getBody(), lambdaGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            return;
        }

        // Если это ветвление IfStmt
        if (node instanceof IfStmt ifStmt) {
            // Вызовы внутри самого условия выполняются при текущем guard
            extractCallsWithGuard(ifStmt.getCondition(), currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);

            String id = branchId(ifStmt);

            // Ветка then
            List<String> thenGuard = new ArrayList<>(currentGuard);
            thenGuard.add(id + ":then");
            extractCallsWithGuard(ifStmt.getThenStmt(), thenGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);

            // Ветка else
            if (ifStmt.getElseStmt().isPresent()) {
                List<String> elseGuard = new ArrayList<>(currentGuard);
                elseGuard.add(id + ":else");
                extractCallsWithGuard(ifStmt.getElseStmt().get(), elseGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
            }
            return;
        }

        // Для всех остальных узлов обходим дочерние узлы с текущим guard
        for (Node child : node.getChildNodes()) {
            extractCallsWithGuard(child, currentGuard, relFile, cu, typeIndex, classMethodNames, resultCalls);
        }
    }

    /** Идентификатор ветки: "b" + строка оператора if. */
    static String branchId(IfStmt ifStmt) {
        return "b" + ifStmt.getBegin().map(p -> p.line).orElse(0);
    }

    private static final Map<Path, List<String>> LINE_CACHE = new HashMap<>();

    /**
     * Колонка начала узла в системе скелета: 1-based смещение в байтах UTF-8.
     * JavaParser считает символы, поэтому строки с кириллицей или иероглифами до вызова сдвигают колонку.
     */
    static int skeletonCol(Node node) {
        Optional<com.github.javaparser.Position> pos = node.getBegin();
        if (pos.isEmpty()) return 0;
        int line = pos.get().line;
        int col = pos.get().column;
        Optional<Path> path = node.findCompilationUnit().flatMap(CompilationUnit::getStorage).map(s -> s.getPath());
        if (path.isEmpty()) return col;
        List<String> lines = LINE_CACHE.computeIfAbsent(path.get(), pth -> {
            try {
                return Files.readAllLines(pth, StandardCharsets.UTF_8);
            } catch (IOException e) {
                return List.of();
            }
        });
        if (line - 1 >= lines.size()) return col;
        String text = lines.get(line - 1);
        int end = Math.min(col - 1, text.length());
        return text.substring(0, end).getBytes(StandardCharsets.UTF_8).length + 1;
    }

    /** Идентификатор try: "t" + строка оператора try. Плечо catch записывается как "t12:catch". */
    static String tryId(TryStmt tryStmt) {
        return "t" + tryStmt.getBegin().map(p -> p.line).orElse(0);
    }

    /** Идентификатор цикла foreach: "f<строка>:<выражение коллекции>", например "f390:orders". */
    static String loopId(ForEachStmt forEach) {
        return "f" + forEach.getBegin().map(p -> p.line).orElse(0) + ":" + forEach.getIterable().toString();
    }

    /** Идентификатор лямбды: "l<строка>:<имя метода, куда лямбда передана>", например "l91:orElseThrow". */
    static String lambdaId(LambdaExpr lambda) {
        String host = lambda.getParentNode()
                .filter(p -> p instanceof MethodCallExpr)
                .map(p -> ((MethodCallExpr) p).getNameAsString())
                .orElse("unknown");
        return "l" + lambda.getBegin().map(p -> p.line).orElse(0) + ":" + host;
    }

    /** Плечи объемлющих if (снаружи внутрь), в которых лежит узел: ["b49:else", "b105:then"]. */
    static List<String> guardOf(Node node) {
        LinkedList<String> guard = new LinkedList<>();
        Node child = node;
        Node parent = node.getParentNode().orElse(null);
        while (parent != null) {
            if (parent instanceof CatchClause && parent.getParentNode().orElse(null) instanceof TryStmt ts) {
                guard.addFirst(tryId(ts) + ":catch");
            } else if (parent instanceof LambdaExpr lambda) {
                guard.addFirst(lambdaId(lambda));
            } else if (parent instanceof ForEachStmt forEach && forEach.getBody() == child) {
                guard.addFirst(loopId(forEach));
            } else if (parent instanceof IfStmt is) {
                if (is.getThenStmt() == child) {
                    guard.addFirst(branchId(is) + ":then");
                } else if (is.getElseStmt().isPresent() && is.getElseStmt().get() == child) {
                    guard.addFirst(branchId(is) + ":else");
                }
            }
            child = parent;
            parent = parent.getParentNode().orElse(null);
        }
        return guard;
    }

    private static boolean isInsideAnonymousClass(Node node) {
        Node current = node.getParentNode().orElse(null);
        while (current != null) {
            if (current instanceof ObjectCreationExpr creation) {
                if (creation.getAnonymousClassBody().isPresent()) {
                    return true;
                }
            }
            current = current.getParentNode().orElse(null);
        }
        return false;
    }

    private static boolean isElseIfChild(IfStmt ifStmt) {
        Optional<Node> parent = ifStmt.getParentNode();
        if (parent.isPresent() && parent.get() instanceof IfStmt parentIf) {
            return parentIf.getElseStmt().isPresent() && parentIf.getElseStmt().get() == ifStmt;
        }
        return false;
    }

    private static void processIfChain(IfStmt ifStmt, CompilationUnit cu, TypeIndex typeIndex, List<BranchIR> branches) {
        IfStmt current = ifStmt;

        while (current != null) {
            int line = current.getBegin().map(p -> p.line).orElse(0);
            String kind = (current == ifStmt) ? "if" : "else-if";
            String conditionText = current.getCondition().toString();
            List<String> refersTo = extractRefersTo(current.getCondition(), typeIndex, cu);
            BranchIR.EarlyExit earlyExit = new BranchIR.EarlyExit(
                    hasEarlyExit(current.getThenStmt()),
                    current.getElseStmt().isPresent() && hasEarlyExit(current.getElseStmt().get()));
            String id = branchId(current);
            List<String> branchGuard = guardOf(current);

            // Некумулятивные вызовы: только вызовы, непосредственно принадлежащие этой ветке (без вложенных if)
            List<String> thenCalls = extractDirectCalls(current.getThenStmt());
            List<String> elseCalls = new ArrayList<>();

            if (current.getElseStmt().isPresent()) {
                Statement elseStmt = current.getElseStmt().get();
                if (elseStmt.isIfStmt()) {
                    BranchIR branch = new BranchIR(id, line, branchGuard, kind, conditionText, refersTo, earlyExit, thenCalls, elseCalls);
                    branches.add(branch);
                    current = elseStmt.asIfStmt();
                } else {
                    // Конечный блок else — фиксируем его прямые вызовы в else_calls последнего плеча
                    elseCalls = extractDirectCalls(elseStmt);
                    BranchIR branch = new BranchIR(id, line, branchGuard, kind, conditionText, refersTo, earlyExit, thenCalls, elseCalls);
                    branches.add(branch);
                    current = null;
                }
            } else {
                BranchIR branch = new BranchIR(id, line, branchGuard, kind, conditionText, refersTo, earlyExit, thenCalls, elseCalls);
                branches.add(branch);
                current = null;
            }
        }
    }

    /**
     * Извлекает координаты вызовов непосредственно из этого блока/оператора,
     * не углубляясь во вложенные IfStmt (чтобы избежать дублирования).
     */
    private static List<String> extractDirectCalls(Statement stmt) {
        List<String> coords = new ArrayList<>();
        if (stmt == null) return coords;

        stmt.walk(node -> {
            // Если узел внутри вложенного IfStmt (кроме самого stmt), не включаем его
            if (node != stmt && isInsideNestedIf(node, stmt)) {
                return;
            }
            if (isInsideAnonymousClass(node)) {
                return;
            }

            if (node instanceof MethodCallExpr call) {
                int line = call.getName().getBegin().map(p -> p.line).orElse(0);
                int col = skeletonCol(call.getName());
                coords.add("cs:" + line + ":" + col);
            } else if (node instanceof ObjectCreationExpr creation) {
                int line = creation.getBegin().map(p -> p.line).orElse(0);
                int col = skeletonCol(creation);
                coords.add("cs:" + line + ":" + col);
            }
        });

        return coords;
    }

    private static boolean isInsideNestedIf(Node node, Statement rootStmt) {
        Node current = node.getParentNode().orElse(null);
        while (current != null && current != rootStmt) {
            if (current instanceof IfStmt) {
                return true;
            }
            current = current.getParentNode().orElse(null);
        }
        return false;
    }

    private static List<String> extractRefersTo(Expression cond, TypeIndex typeIndex, CompilationUnit cu) {
        Set<String> refers = new LinkedHashSet<>();

        cond.walk(node -> {
            if (node instanceof MethodCallExpr call) {
                EnumConstantIR ec = EnumResolver.resolveCall(call, cu);
                if (ec != null) {
                    refers.add("enum:" + getSimpleEnumName(ec.getType()) + "." + ec.getConstant());
                } else if (call.getScope().isPresent()) {
                    Expression scope = call.getScope().get();
                    String propName = TypeIndex.extractPropertyName(call.getNameAsString());
                    if (propName != null) {
                        String scopeStr = scope.toString();
                        String type = typeIndex.resolveVariableType(node, scopeStr);
                        if (type != null) {
                            refers.add("field:" + type + "." + propName);
                        } else {
                            refers.add("field:" + scopeStr + "." + propName);
                        }
                    }
                }
            } else if (node instanceof FieldAccessExpr fae) {
                EnumConstantIR ec = EnumResolver.resolveExpression(fae, cu);
                if (ec != null) {
                    refers.add("enum:" + getSimpleEnumName(ec.getType()) + "." + ec.getConstant());
                } else {
                    String scopeStr = fae.getScope().toString();
                    String fieldName = fae.getNameAsString();
                    String type = typeIndex.resolveVariableType(node, scopeStr);
                    if (type != null) {
                        refers.add("field:" + type + "." + fieldName);
                    }
                }
            } else if (node instanceof NameExpr ne) {
                String name = ne.getNameAsString();
                EnumConstantIR ec = EnumResolver.resolveExpression(ne, cu);
                if (ec != null) {
                    refers.add("enum:" + getSimpleEnumName(ec.getType()) + "." + ec.getConstant());
                } else if (typeIndex.isLocalOrParam(node, name)) {
                    refers.add("local:" + name);
                } else if (typeIndex.isField(name)) {
                    refers.add("field:" + typeIndex.getClassName() + "." + name);
                }
            }
        });

        return new ArrayList<>(refers);
    }

    private static String getSimpleEnumName(String fqn) {
        int idx = fqn.lastIndexOf('.');
        return idx >= 0 ? fqn.substring(idx + 1) : fqn;
    }

    private static boolean hasEarlyExit(Statement stmt) {
        if (stmt == null) return false;
        if (stmt.isReturnStmt() || stmt.isThrowStmt()) return true;

        if (stmt.isIfStmt()) {
            IfStmt ifStmt = stmt.asIfStmt();
            return ifStmt.getElseStmt().isPresent()
                    && hasEarlyExit(ifStmt.getThenStmt())
                    && hasEarlyExit(ifStmt.getElseStmt().get());
        }

        if (stmt.isBlockStmt()) {
            BlockStmt block = stmt.asBlockStmt();
            for (Statement s : block.getStatements()) {
                if (s.isReturnStmt() || s.isThrowStmt()) {
                    return true;
                }
                if (s.isIfStmt()) {
                    IfStmt ifStmt = s.asIfStmt();
                    if (ifStmt.getElseStmt().isPresent() &&
                            hasEarlyExit(ifStmt.getThenStmt()) &&
                            hasEarlyExit(ifStmt.getElseStmt().get())) {
                        return true;
                    }
                }
            }
        }

        return false;
    }
}
