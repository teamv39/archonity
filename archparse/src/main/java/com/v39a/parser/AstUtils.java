package com.v39a.parser;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.expr.LambdaExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.TryStmt;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

/**
 * Общие вспомогательные методы для работы с AST:
 * вычисление колонок в байтах UTF-8 для call_site скелета,
 * формирование строковых идентификаторов операторов и узлов.
 */
public final class AstUtils {

    private static final Map<Path, List<String>> LINE_CACHE = new HashMap<>();

    private AstUtils() {}

    /** Идентификатор ветки: "b" + строка оператора if. */
    public static String branchId(IfStmt ifStmt) {
        return "b" + ifStmt.getBegin().map(p -> p.line).orElse(0);
    }

    /**
     * Колонка начала узла в системе скелета: 1-based смещение в байтах UTF-8.
     * JavaParser считает символы, поэтому строки с кириллицей или иероглифами до вызова сдвигают колонку.
     */
    public static int skeletonCol(Node node) {
        Optional<com.github.javaparser.Position> pos = node.getBegin();
        if (pos.isEmpty()) return 0;
        return skeletonCol(node, pos.get().line, pos.get().column);
    }

    /** То же для произвольной позиции (строка, колонка в символах) в файле узла. */
    public static int skeletonCol(Node node, int line, int col) {
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
    public static String tryId(TryStmt tryStmt) {
        return "t" + tryStmt.getBegin().map(p -> p.line).orElse(0);
    }

    /** Идентификатор цикла foreach: "f<строка>:<выражение коллекции>", например "f390:orders". */
    public static String loopId(ForEachStmt forEach) {
        return "f" + forEach.getBegin().map(p -> p.line).orElse(0) + ":" + forEach.getIterable().toString();
    }

    /** Идентификатор лямбды: "l<строка>:<имя метода, куда лямбда передана>", например "l91:orElseThrow". */
    public static String lambdaId(LambdaExpr lambda) {
        String host = lambda.getParentNode()
                .filter(p -> p instanceof MethodCallExpr)
                .map(p -> ((MethodCallExpr) p).getNameAsString())
                .orElse("unknown");
        return "l" + lambda.getBegin().map(p -> p.line).orElse(0) + ":" + host;
    }
}
