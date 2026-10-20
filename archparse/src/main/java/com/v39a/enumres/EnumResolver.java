package com.v39a.enumres;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.body.EnumConstantDeclaration;
import com.github.javaparser.ast.body.EnumDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.v39a.model.EnumConstantIR;
import com.v39a.parser.ProjectIndex;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Stream;

/**
 * Универсальный резолвер констант перечислений (enum).
 * Автоматически индексирует все перечисления проекта и сопоставляет
 * обращения к константам (FieldAccessExpr, NameExpr со static import, MethodCallExpr).
 */
public class EnumResolver {

    private static final Map<String, Set<String>> ENUM_CONSTANTS = new ConcurrentHashMap<>();
    private static final Map<String, List<String>> FQNS_BY_SIMPLE = new ConcurrentHashMap<>();
    private static volatile boolean initialized = false;

    /** Регистрация перечисления и его констант. */
    public static void registerEnum(String fqn, Set<String> constants) {
        if (fqn == null || constants == null) return;
        ENUM_CONSTANTS.put(fqn, Collections.unmodifiableSet(new HashSet<>(constants)));
        String simple = fqn.substring(fqn.lastIndexOf('.') + 1).replace('$', '.');
        if (simple.contains(".")) {
            String shortSimple = simple.substring(simple.lastIndexOf('.') + 1);
            FQNS_BY_SIMPLE.computeIfAbsent(shortSimple, k -> new ArrayList<>()).add(fqn);
        }
        FQNS_BY_SIMPLE.computeIfAbsent(simple, k -> new ArrayList<>()).add(fqn);
    }

    /** Инициализация из ProjectIndex. */
    public static void initFrom(ProjectIndex projectIndex) {
        // ProjectIndex уже содержит все типы проекта
        initialized = true;
    }

    /** Сканирование всех enum в директории исходников проекта. */
    public static synchronized void scanEnums(Path targetsDir) {
        if (targetsDir == null || !Files.exists(targetsDir)) return;
        try (Stream<Path> stream = Files.walk(targetsDir)) {
            stream.filter(p -> p.toString().endsWith(".java")).forEach(path -> {
                try {
                    // Быстрая проверка наличия enum перед полным парсингом
                    String content = Files.readString(path);
                    if (!content.contains("enum ")) return;

                    CompilationUnit cu = StaticJavaParser.parse(path);
                    indexCompilationUnit(cu);
                } catch (Exception ignored) {
                }
            });
            initialized = true;
        } catch (IOException ignored) {
        }
    }

    public static void indexCompilationUnit(CompilationUnit cu) {
        if (cu == null) return;
        String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
        for (EnumDeclaration ed : cu.findAll(EnumDeclaration.class)) {
            String fqn = binaryName(pkg, ed);
            Set<String> constants = new HashSet<>();
            for (EnumConstantDeclaration ecd : ed.getEntries()) {
                constants.add(ecd.getNameAsString());
            }
            registerEnum(fqn, constants);
        }
    }

    private static void ensureInitialized(CompilationUnit cu) {
        if (initialized && !ENUM_CONSTANTS.isEmpty()) {
            if (cu != null) indexCompilationUnit(cu);
            return;
        }
        synchronized (EnumResolver.class) {
            if (initialized && !ENUM_CONSTANTS.isEmpty()) {
                if (cu != null) indexCompilationUnit(cu);
                return;
            }

            if (cu != null) {
                indexCompilationUnit(cu);
            }

            Path targetsDir = resolveDefaultTargetsDir();
            if (targetsDir != null) {
                scanEnums(targetsDir);
            }
            initialized = true;
        }
    }

    private static Path resolveDefaultTargetsDir() {
        String[] candidates = {
                "hackaton/tt-challenge/targets/trainticket",
                "../hackaton/tt-challenge/targets/trainticket",
                "data/train-ticket",
                "../data/train-ticket"
        };
        for (String cand : candidates) {
            Path p = Paths.get(cand);
            if (Files.isDirectory(p)) {
                return p;
            }
        }
        return null;
    }

    private static String binaryName(String pkg, TypeDeclaration<?> td) {
        Deque<String> names = new ArrayDeque<>();
        com.github.javaparser.ast.Node cur = td;
        while (cur != null) {
            if (cur instanceof TypeDeclaration<?> t) {
                names.addFirst(t.getNameAsString());
            }
            cur = cur.getParentNode().orElse(null);
        }
        String name = String.join("$", names);
        return pkg.isEmpty() ? name : pkg + "." + name;
    }

    /**
     * Проверяет, является ли вызов метода вызовом на enum-константе.
     * Если да, возвращает EnumConstantIR, иначе null.
     */
    public static EnumConstantIR resolveCall(MethodCallExpr call, CompilationUnit cu) {
        if (call == null || !call.getScope().isPresent()) {
            return null;
        }
        return resolveExpression(call.getScope().get(), cu);
    }

    /**
     * Проверяет выражение на принадлежность к известной enum-константе.
     */
    public static EnumConstantIR resolveExpression(Expression expr, CompilationUnit cu) {
        if (expr == null) {
            return null;
        }

        ensureInitialized(cu);

        if (expr.isFieldAccessExpr()) {
            FieldAccessExpr fae = expr.asFieldAccessExpr();
            String constName = fae.getNameAsString();
            String scopeStr = fae.getScope().toString();

            String enumFqn = resolveEnumFqn(scopeStr, cu);
            if (enumFqn != null) {
                Set<String> constants = ENUM_CONSTANTS.get(enumFqn);
                if (constants != null && constants.contains(constName)) {
                    return new EnumConstantIR(enumFqn, constName);
                }
            }
        } else if (expr.isNameExpr()) {
            String name = expr.asNameExpr().getNameAsString();
            String enumFqn = resolveStaticImportEnum(name, cu);
            if (enumFqn != null) {
                Set<String> constants = ENUM_CONSTANTS.get(enumFqn);
                if (constants != null && constants.contains(name)) {
                    return new EnumConstantIR(enumFqn, name);
                }
            }
        }

        return null;
    }

    public static boolean isKnownEnumConstant(String type, String constant) {
        ensureInitialized(null);
        Set<String> constants = ENUM_CONSTANTS.get(type);
        return constants != null && constants.contains(constant);
    }

    private static String resolveEnumFqn(String scopeStr, CompilationUnit cu) {
        if (ENUM_CONSTANTS.containsKey(scopeStr)) {
            return scopeStr;
        }

        if (cu != null) {
            // 1. Явные импорты
            for (ImportDeclaration imp : cu.getImports()) {
                if (!imp.isStatic() && !imp.isAsterisk()) {
                    String impFqn = imp.getNameAsString();
                    if (impFqn.endsWith("." + scopeStr)) {
                        String binary = impFqn.replace('.', '$');
                        if (ENUM_CONSTANTS.containsKey(impFqn)) return impFqn;
                        for (String fqn : ENUM_CONSTANTS.keySet()) {
                            if (fqn.replace('$', '.').equals(impFqn)) return fqn;
                        }
                    }
                }
            }

            // 2. Текущий пакет
            String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
            String localFqn = pkg.isEmpty() ? scopeStr : pkg + "." + scopeStr;
            if (ENUM_CONSTANTS.containsKey(localFqn)) {
                return localFqn;
            }

            // 3. Wildcard импорты
            for (ImportDeclaration imp : cu.getImports()) {
                if (!imp.isStatic() && imp.isAsterisk()) {
                    String candidate = imp.getNameAsString() + "." + scopeStr;
                    if (ENUM_CONSTANTS.containsKey(candidate)) return candidate;
                    for (String fqn : ENUM_CONSTANTS.keySet()) {
                        if (fqn.replace('$', '.').equals(candidate)) return fqn;
                    }
                }
            }
        }

        // 4. Поиск по простому имени
        List<String> candidates = FQNS_BY_SIMPLE.get(scopeStr);
        if (candidates != null && !candidates.isEmpty()) {
            if (candidates.size() == 1) {
                return candidates.get(0);
            }
            // Если кандидатов несколько, предпочитаем ts-common или edu.fudan
            for (String cand : candidates) {
                if (cand.contains("edu.fudan.common")) {
                    return cand;
                }
            }
            return candidates.get(0);
        }

        return null;
    }

    private static String resolveStaticImportEnum(String constName, CompilationUnit cu) {
        if (cu == null) return null;
        for (ImportDeclaration imp : cu.getImports()) {
            if (imp.isStatic()) {
                String impName = imp.getNameAsString();
                if (imp.isAsterisk()) {
                    if (ENUM_CONSTANTS.containsKey(impName)) {
                        Set<String> constants = ENUM_CONSTANTS.get(impName);
                        if (constants != null && constants.contains(constName)) {
                            return impName;
                        }
                    }
                } else if (impName.endsWith("." + constName)) {
                    String enumFqn = impName.substring(0, impName.lastIndexOf('.'));
                    if (ENUM_CONSTANTS.containsKey(enumFqn)) {
                        return enumFqn;
                    }
                }
            }
        }
        return null;
    }
}
