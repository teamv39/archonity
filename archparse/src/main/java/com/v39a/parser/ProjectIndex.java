package com.v39a.parser;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.*;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.LiteralExpr;
import com.github.javaparser.ast.expr.UnaryExpr;

import java.util.*;

/**
 * Индекс всего проекта для IR тел методов: типы по простому имени, константы enum
 * с аргументами из объявления, поля static final с литералом.
 */
public class ProjectIndex {

    /** Тип проекта: FQN в записи скелета (вложенные через '$'), модуль. */
    public record TypeInfo(String fqn, String module, String pkg) {}

    private final Map<String, List<TypeInfo>> typesBySimple = new HashMap<>();
    private final Map<String, Map<String, List<Expression>>> enumConstants = new HashMap<>();
    private final Map<String, Map<String, Expression>> constants = new HashMap<>();

    /** Добавляет все типы файла. */
    public void add(CompilationUnit cu, String module) {
        String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
        for (TypeDeclaration<?> td : cu.findAll(TypeDeclaration.class)) {
            String fqn = binaryName(pkg, td);
            typesBySimple.computeIfAbsent(td.getNameAsString(), k -> new ArrayList<>()).add(new TypeInfo(fqn, module, pkg));
            if (td instanceof EnumDeclaration ed) {
                Map<String, List<Expression>> cs = new LinkedHashMap<>();
                for (EnumConstantDeclaration c : ed.getEntries()) {
                    cs.put(c.getNameAsString(), new ArrayList<>(c.getArguments()));
                }
                enumConstants.put(fqn, cs);
            }
            boolean iface = td instanceof ClassOrInterfaceDeclaration cid && cid.isInterface();
            for (FieldDeclaration fd : td.getFields()) {
                if (!(iface || (fd.isStatic() && fd.isFinal()))) {
                    continue;
                }
                for (VariableDeclarator vd : fd.getVariables()) {
                    vd.getInitializer().filter(ProjectIndex::isLiteral).ifPresent(init ->
                            constants.computeIfAbsent(fqn, k -> new HashMap<>()).put(vd.getNameAsString(), init));
                }
            }
        }
    }

    static boolean isLiteral(Expression e) {
        return e instanceof LiteralExpr
                || (e instanceof UnaryExpr u && u.getOperator() == UnaryExpr.Operator.MINUS && u.getExpression() instanceof LiteralExpr);
    }

    /** Двоичное имя типа как в ID скелета: вложенные типы через '$'. */
    static String binaryName(String pkg, Node td) {
        Deque<String> names = new ArrayDeque<>();
        Node cur = td;
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
     * FQN типа проекта по простому имени из файла: явный импорт, тот же пакет, импорт пакета со звёздочкой,
     * тот же модуль, ts-common. null — тип не из проекта.
     */
    public String resolveType(String simple, CompilationUnit cu, String module) {
        List<TypeInfo> cands = typesBySimple.get(simple);
        if (cands == null) {
            return null;
        }
        for (ImportDeclaration imp : cu.getImports()) {
            if (!imp.isStatic() && !imp.isAsterisk() && imp.getNameAsString().endsWith("." + simple)) {
                String imported = imp.getNameAsString();
                for (TypeInfo t : cands) {
                    if (t.fqn().replace('$', '.').equals(imported)) {
                        return t.fqn();
                    }
                }
                return null; // импортирован тип не из проекта
            }
        }
        String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
        for (TypeInfo t : cands) {
            if (t.pkg().equals(pkg) && t.module().equals(module)) {
                return t.fqn();
            }
        }
        for (ImportDeclaration imp : cu.getImports()) {
            if (!imp.isStatic() && imp.isAsterisk()) {
                for (TypeInfo t : cands) {
                    if (t.pkg().equals(imp.getNameAsString())) {
                        return t.fqn();
                    }
                }
            }
        }
        for (TypeInfo t : cands) {
            if (t.module().equals(module)) {
                return t.fqn();
            }
        }
        for (TypeInfo t : cands) {
            if (t.module().equals("ts-common")) {
                return t.fqn();
            }
        }
        return null;
    }

    public boolean isEnum(String fqn) {
        return fqn != null && enumConstants.containsKey(fqn);
    }

    /** Аргументы константы enum в объявлении или null, если такой константы нет. */
    public List<Expression> enumConstant(String enumFqn, String constant) {
        Map<String, List<Expression>> cs = enumConstants.get(enumFqn);
        return cs == null ? null : cs.get(constant);
    }

    /** Enum, в котором константа с таким именем единственная (для меток case без квалификатора). */
    public String uniqueEnumOf(String constant) {
        String found = null;
        for (Map.Entry<String, Map<String, List<Expression>>> e : enumConstants.entrySet()) {
            if (e.getValue().containsKey(constant)) {
                if (found != null) {
                    return null;
                }
                found = e.getKey();
            }
        }
        return found;
    }

    /** Литерал static final поля типа или null. */
    public Expression constant(String typeFqn, String field) {
        Map<String, Expression> cs = constants.get(typeFqn);
        return cs == null ? null : cs.get(field);
    }
}
