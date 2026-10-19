package com.v39a.parser;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.CallableDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.v39a.skeleton.SkeletonGraph;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * IR тел всех методов скелета (README, раздел 3.6): по файлу data/ir/<module>.json на модуль.
 * Заодно считает покрытие: каждый метод скелета с телом найден, каждый call_site встретился один раз.
 */
public class MethodIrWriter {

    public static final String SCHEMA = "method_ir/1";

    /** Итог прогона: IR по модулям и проверка покрытия скелета. */
    public static class Result {
        public final Map<String, ObjectNode> modules = new TreeMap<>();
        public int methods;
        public int irCalls;
        public int callSites;
        public final List<String> missingMethods = new ArrayList<>();
        public final List<String> unmatchedDeclarations = new ArrayList<>();
        public final List<String> uncoveredCallSites = new ArrayList<>();
        public final List<String> duplicateCallSites = new ArrayList<>();
        public final List<String> foreignCallSites = new ArrayList<>();
    }

    private record Source(String rel, String module, CompilationUnit cu) {}

    public static Result build(Path targetsDir, SkeletonGraph skeleton) throws IOException {
        List<Source> sources = parseAll(targetsDir);
        ProjectIndex project = new ProjectIndex();
        for (Source s : sources) {
            project.add(s.cu(), s.module());
        }

        Result r = new Result();
        Map<String, Map<String, ObjectNode>> byModule = new TreeMap<>();
        Set<String> matched = new HashSet<>();
        for (Source s : sources) {
            if (skeleton.methodsInFile(s.rel()).isEmpty()) {
                continue; // файл вне модулей скелета (old-docs и т. п.)
            }
            for (CallableDeclaration<?> decl : s.cu().findAll(CallableDeclaration.class)) {
                BlockStmt body = bodyOf(decl);
                if (body == null) {
                    continue;
                }
                SkeletonGraph.MethodNode node = match(skeleton, s.rel(), decl);
                if (node == null) {
                    r.unmatchedDeclarations.add(s.rel() + ":" + BodyIrBuilder.line(decl) + " " + decl.getDeclarationAsString(false, false, false));
                    continue;
                }
                matched.add(node.id());
                BodyIrBuilder b = new BodyIrBuilder(skeleton, project, s.cu(), s.module(), s.rel(), node, decl);
                byModule.computeIfAbsent(node.module(), k -> new TreeMap<>()).put(node.id(), b.build(decl, body));
                r.methods++;
                r.irCalls += b.irCalls();
                coverage(r, skeleton, node, b.callSitesSeen());
            }
        }
        for (SkeletonGraph.MethodNode m : skeleton.methods()) {
            if (!m.isAbstract() && !matched.contains(m.id())) {
                r.missingMethods.add(m.id());
            }
        }
        for (Map.Entry<String, Map<String, ObjectNode>> e : byModule.entrySet()) {
            ObjectNode doc = JsonNodeFactory.instance.objectNode();
            doc.put("schema", SCHEMA);
            doc.put("module", e.getKey());
            ObjectNode methods = doc.putObject("methods");
            e.getValue().forEach(methods::set);
            r.modules.put(e.getKey(), doc);
        }
        return r;
    }

    private static void coverage(Result r, SkeletonGraph skeleton, SkeletonGraph.MethodNode node, List<String> seen) {
        Set<String> expected = skeleton.callSitesOf(node.id());
        Set<String> uniq = new HashSet<>();
        for (String cs : seen) {
            if (!uniq.add(cs)) {
                r.duplicateCallSites.add(cs);
            } else if (!expected.contains(cs)) {
                r.foreignCallSites.add(cs);
            }
        }
        r.callSites += uniq.size();
        for (String cs : expected) {
            if (!uniq.contains(cs)) {
                r.uncoveredCallSites.add(cs);
            }
        }
    }

    private static BlockStmt bodyOf(CallableDeclaration<?> decl) {
        if (decl instanceof MethodDeclaration md) {
            return md.getBody().orElse(null);
        }
        if (decl instanceof ConstructorDeclaration cd) {
            return cd.getBody();
        }
        return null;
    }

    /** Метод скелета: тот же файл, имя, число параметров, строка объявления между началом (с аннотациями) и именем. */
    static SkeletonGraph.MethodNode match(SkeletonGraph skeleton, String rel, CallableDeclaration<?> decl) {
        String name = decl instanceof ConstructorDeclaration ? "<init>" : decl.getNameAsString();
        int from = BodyIrBuilder.line(decl);
        int to = BodyIrBuilder.line(decl.getName());
        SkeletonGraph.MethodNode found = null;
        for (SkeletonGraph.MethodNode m : skeleton.methodsInFile(rel)) {
            if (!m.isAbstract() && m.name().equals(name) && m.paramCount() == decl.getParameters().size()
                    && m.line() >= from && m.line() <= to) {
                if (found != null) {
                    return null;
                }
                found = m;
            }
        }
        return found;
    }

    private static List<Source> parseAll(Path targetsDir) throws IOException {
        List<Path> files;
        try (Stream<Path> walk = Files.walk(targetsDir)) {
            files = walk.filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> rel(targetsDir, p).contains("/src/main/java/"))
                    .sorted().collect(Collectors.toList());
        }
        ThreadLocal<com.github.javaparser.JavaParser> parser = ThreadLocal.withInitial(com.github.javaparser.JavaParser::new);
        return files.parallelStream().map(p -> {
            String rel = rel(targetsDir, p);
            try {
                return parser.get().parse(p).getResult()
                        .map(cu -> new Source(rel, rel.substring(0, rel.indexOf('/')), cu))
                        .orElse(null);
            } catch (Exception e) {
                System.err.println("Parse error, skipped: " + rel + ": " + e.getMessage());
                return null;
            }
        }).filter(Objects::nonNull).collect(Collectors.toList());
    }

    private static String rel(Path root, Path p) {
        return root.relativize(p).toString().replace('\\', '/');
    }
}
