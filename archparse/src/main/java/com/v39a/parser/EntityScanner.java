package com.v39a.parser;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.body.*;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.stmt.*;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.Type;
import com.v39a.model.EntityReportIR;
import com.v39a.model.MethodIR;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * Сканер сущностей JPA и вызовов репозиториев Spring Data по всему проекту.
 *
 * Даёт движку факты для правила R7 (конструктор сущности при загрузке строк Hibernate):
 * какой сущности принадлежит вызов репозитория, читает он или пишет, ждёт ли успешный путь
 * метода найденную строку или её отсутствие, и что делает конструктор без аргументов.
 * Таблицы, данные и решение «исполнился ли конструктор» — на стороне движка.
 */
public class EntityScanner {

    private static final Set<String> SPRING_DATA_REPOSITORIES = Set.of(
            "Repository", "CrudRepository", "JpaRepository", "PagingAndSortingRepository", "MongoRepository");
    private static final Set<String> ENTITY_ANNOTATIONS = Set.of("Entity", "Embeddable", "Document");
    private static final Set<String> COLLECTION_TYPES = Set.of(
            "List", "ArrayList", "Set", "HashSet", "Collection", "Map", "HashMap", "LinkedList");

    private final Path targetsDir;

    /** Разобранный файл проекта. */
    private record SourceFile(String relFile, String module, CompilationUnit cu) {}

    /** Описание интерфейса репозитория. */
    private record RepoInfo(String module, String name, String entitySimple, CompilationUnit cu, Set<String> modifying) {}

    /** Сущность с её объявлением (для разбора конструкторов и полей). */
    private record EntityDecl(EntityReportIR.Entity ir, ClassOrInterfaceDeclaration cid, CompilationUnit cu) {}

    public EntityScanner(Path targetsDir) {
        this.targetsDir = targetsDir;
    }

    public EntityReportIR scan() throws IOException {
        List<SourceFile> files = parseAll();

        Map<String, EntityDecl> entitiesByFqn = new LinkedHashMap<>();
        Map<String, RepoInfo> repos = new HashMap<>(); // module + ":" + имя интерфейса
        EntityReportIR report = new EntityReportIR();

        // Проход 1: сущности, репозитории, конструкторы без аргументов
        for (SourceFile sf : files) {
            String pkg = sf.cu().getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
            for (ClassOrInterfaceDeclaration cid : sf.cu().findAll(ClassOrInterfaceDeclaration.class)) {
                String fqn = binaryName(pkg, cid);
                if (cid.isInterface()) {
                    RepoInfo repo = repositoryInfo(sf, cid);
                    if (repo != null) {
                        repos.put(sf.module() + ":" + cid.getNameAsString(), repo);
                    }
                    continue;
                }
                String entityKind = entityKind(cid);
                if (entityKind != null) {
                    EntityReportIR.Entity e = describeEntity(sf, cid, fqn, entityKind);
                    entitiesByFqn.put(fqn, new EntityDecl(e, cid, sf.cu()));
                }
                noArgConstructor(cid).ifPresent(cd -> report.noArgCtorStatements.put(
                        "method:" + sf.module() + ":" + fqn + "#<init>()", cd.getBody().getStatements().size()));
                MethodIR ctorIr = noArgConstructorIr(sf, cid, fqn);
                if (ctorIr != null) {
                    report.constructors.add(ctorIr);
                }
            }
        }

        // Встраиваемые поля сущностей: тип резолвим по известным встраиваемым классам
        Map<String, String> embeddableBySimple = new HashMap<>();
        for (EntityDecl ed : entitiesByFqn.values()) {
            if ("Embeddable".equals(ed.ir().kind)) {
                embeddableBySimple.put(simpleName(ed.ir().type), ed.ir().type);
            }
        }
        for (EntityDecl ed : entitiesByFqn.values()) {
            for (FieldDeclaration fd : ed.cid().getFields()) {
                if (fd.isStatic() || isCollection(fd.getElementType())) {
                    continue;
                }
                String simple = baseName(fd.getElementType().asString());
                boolean embeddedAnn = fd.isAnnotationPresent("Embedded") || fd.isAnnotationPresent("EmbeddedId");
                if (embeddedAnn || embeddableBySimple.containsKey(simple)) {
                    String target = embeddableBySimple.containsKey(simple)
                            ? embeddableBySimple.get(simple) : importedFqn(ed.cu(), simple);
                    if (!ed.ir().embedded.contains(target)) {
                        ed.ir().embedded.add(target);
                    }
                }
            }
            report.entities.add(ed.ir());
        }

        // Проход 2: вызовы репозиториев во всех классах проекта
        for (SourceFile sf : files) {
            for (ClassOrInterfaceDeclaration cid : sf.cu().findAll(ClassOrInterfaceDeclaration.class)) {
                if (cid.isInterface()) {
                    continue;
                }
                Map<String, RepoInfo> repoFields = new HashMap<>();
                for (FieldDeclaration fd : cid.getFields()) {
                    RepoInfo repo = repos.get(sf.module() + ":" + baseName(fd.getElementType().asString()));
                    if (repo != null) {
                        for (VariableDeclarator vd : fd.getVariables()) {
                            repoFields.put(vd.getNameAsString(), repo);
                        }
                    }
                }
                if (repoFields.isEmpty()) {
                    continue;
                }
                for (MethodCallExpr call : cid.findAll(MethodCallExpr.class)) {
                    if (call.findAncestor(ClassOrInterfaceDeclaration.class).orElse(null) != cid) {
                        continue; // вызов во вложенном классе разберётся при его обходе
                    }
                    String field = repositoryFieldOf(call);
                    RepoInfo repo = field == null ? null : repoFields.get(field);
                    if (repo == null) {
                        continue;
                    }
                    EntityDecl entity = resolveEntity(repo, entitiesByFqn);
                    report.repositoryCalls.add(describeCall(sf, call, repo, entity));
                }
            }
        }

        report.entities.sort(Comparator.comparing(e -> e.type));
        report.constructors.sort(Comparator.comparing(MethodIR::getMethodId));
        report.repositoryCalls.sort(Comparator.<EntityReportIR.RepositoryCall, String>comparing(c -> c.file)
                .thenComparingInt(c -> c.line).thenComparingInt(c -> c.col));
        return report;
    }

    // ------------------------------------------------------------------
    // Разбор файлов
    // ------------------------------------------------------------------

    private List<SourceFile> parseAll() throws IOException {
        List<Path> javaFiles;
        try (Stream<Path> walk = Files.walk(targetsDir)) {
            javaFiles = walk.filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> {
                        String rel = rel(p);
                        return rel.contains("/src/main/java/");
                    })
                    .sorted()
                    .collect(Collectors.toList());
        }
        List<SourceFile> out = new ArrayList<>();
        for (Path p : javaFiles) {
            String rel = rel(p);
            try {
                CompilationUnit cu = StaticJavaParser.parse(p);
                out.add(new SourceFile(rel, rel.substring(0, rel.indexOf('/')), cu));
            } catch (Exception e) {
                System.err.println("Parse error, skipped: " + rel + ": " + e.getMessage());
            }
        }
        return out;
    }

    private String rel(Path p) {
        return targetsDir.relativize(p).toString().replace('\\', '/');
    }

    /** Двоичное имя класса как в ID скелета: вложенные классы через '$'. */
    static String binaryName(String pkg, ClassOrInterfaceDeclaration cid) {
        Deque<String> names = new ArrayDeque<>();
        Node cur = cid;
        while (cur != null) {
            if (cur instanceof ClassOrInterfaceDeclaration c) {
                names.addFirst(c.getNameAsString());
            }
            cur = cur.getParentNode().orElse(null);
        }
        String name = String.join("$", names);
        return pkg.isEmpty() ? name : pkg + "." + name;
    }

    // ------------------------------------------------------------------
    // Сущности
    // ------------------------------------------------------------------

    private static String entityKind(ClassOrInterfaceDeclaration cid) {
        for (AnnotationExpr a : cid.getAnnotations()) {
            if (ENTITY_ANNOTATIONS.contains(a.getNameAsString())) {
                return a.getNameAsString();
            }
        }
        return null;
    }

    private static EntityReportIR.Entity describeEntity(SourceFile sf, ClassOrInterfaceDeclaration cid, String fqn, String kind) {
        EntityReportIR.Entity e = new EntityReportIR.Entity();
        e.type = fqn;
        e.module = sf.module();
        e.file = sf.relFile();
        e.kind = kind;
        if (!"Embeddable".equals(kind)) {
            e.table = tableName(cid);
        }

        for (FieldDeclaration fd : cid.getFields()) {
            if (fd.isAnnotationPresent("Id") || fd.isAnnotationPresent("EmbeddedId")) {
                e.idField = fd.getVariable(0).getNameAsString();
                e.idGenerated = fd.isAnnotationPresent("GeneratedValue");
            }
        }

        Optional<ConstructorDeclaration> ctor = noArgConstructor(cid);
        if (ctor.isPresent()) {
            e.noArgCtor = "method:" + sf.module() + ":" + fqn + "#<init>()";
            e.ctorStatements = ctor.get().getBody().getStatements().size();
            e.ctorAssignsId = e.idField != null && assignsField(ctor.get().getBody(), e.idField);
        }
        return e;
    }

    /** Имя таблицы: @Table(name) или правило SpringPhysicalNamingStrategy для имени класса. */
    static String tableName(ClassOrInterfaceDeclaration cid) {
        Optional<AnnotationExpr> table = cid.getAnnotationByName("Table");
        if (table.isPresent()) {
            String name = annotationAttr(table.get(), "name");
            if (name != null && !name.isEmpty()) {
                return name;
            }
        }
        return springPhysicalName(cid.getNameAsString());
    }

    /** CamelCase -> snake_case по правилу Spring Boot: '_' между строчной, заглавной и строчной буквой. */
    public static String springPhysicalName(String name) {
        StringBuilder sb = new StringBuilder(name);
        for (int i = 1; i < sb.length() - 1; i++) {
            if (Character.isLowerCase(sb.charAt(i - 1)) && Character.isUpperCase(sb.charAt(i))
                    && Character.isLowerCase(sb.charAt(i + 1))) {
                sb.insert(i++, '_');
            }
        }
        return sb.toString().toLowerCase(Locale.ROOT);
    }

    private static String annotationAttr(AnnotationExpr a, String attr) {
        if (a instanceof NormalAnnotationExpr na) {
            for (MemberValuePair p : na.getPairs()) {
                if (p.getNameAsString().equals(attr) && p.getValue() instanceof StringLiteralExpr s) {
                    return s.getValue();
                }
            }
        } else if (a instanceof SingleMemberAnnotationExpr sa && "value".equals(attr)
                && sa.getMemberValue() instanceof StringLiteralExpr s) {
            return s.getValue();
        }
        return null;
    }

    private static Optional<ConstructorDeclaration> noArgConstructor(ClassOrInterfaceDeclaration cid) {
        return cid.getConstructors().stream().filter(c -> c.getParameters().isEmpty()).findFirst();
    }

    private static boolean assignsField(Node body, String field) {
        for (AssignExpr a : body.findAll(AssignExpr.class)) {
            Expression t = a.getTarget();
            if (t instanceof NameExpr n && n.getNameAsString().equals(field)) {
                return true;
            }
            if (t instanceof FieldAccessExpr f && f.getScope() instanceof ThisExpr && f.getNameAsString().equals(field)) {
                return true;
            }
        }
        return false;
    }

    /** IR тела явного конструктора без аргументов, если в нём есть вызовы. */
    private static MethodIR noArgConstructorIr(SourceFile sf, ClassOrInterfaceDeclaration cid, String fqn) {
        Optional<ConstructorDeclaration> ctor = noArgConstructor(cid);
        if (ctor.isEmpty()) {
            return null;
        }
        String id = "method:" + sf.module() + ":" + fqn + "#<init>()";
        MethodIR ir = AstAnalyzer.analyzeConstructor(id, sf.relFile(), ctor.get(), sf.cu(), new TypeIndex(sf.cu(), cid));
        return ir.getCalls().isEmpty() ? null : ir;
    }

    // ------------------------------------------------------------------
    // Репозитории
    // ------------------------------------------------------------------

    private static RepoInfo repositoryInfo(SourceFile sf, ClassOrInterfaceDeclaration cid) {
        for (ClassOrInterfaceType ext : cid.getExtendedTypes()) {
            if (!SPRING_DATA_REPOSITORIES.contains(ext.getNameAsString())) {
                continue;
            }
            Optional<NodeList<Type>> args = ext.getTypeArguments();
            if (args.isEmpty() || args.get().isEmpty()) {
                return null;
            }
            Set<String> modifying = new HashSet<>();
            for (MethodDeclaration md : cid.getMethods()) {
                if (md.isAnnotationPresent("Modifying")) {
                    modifying.add(md.getNameAsString());
                }
            }
            return new RepoInfo(sf.module(), cid.getNameAsString(), baseName(args.get().get(0).asString()), sf.cu(), modifying);
        }
        return null;
    }

    /** Полное имя типа по явному импорту файла, иначе тот же пакет. */
    private static String importedFqn(CompilationUnit cu, String simple) {
        for (ImportDeclaration imp : cu.getImports()) {
            if (!imp.isAsterisk() && !imp.isStatic() && imp.getNameAsString().endsWith("." + simple)) {
                return imp.getNameAsString();
            }
        }
        return cu.getPackageDeclaration().map(p -> p.getNameAsString() + "." + simple).orElse(simple);
    }

    /** Сущность репозитория: явный импорт, затем тот же модуль, затем ts-common. */
    private static EntityDecl resolveEntity(RepoInfo repo, Map<String, EntityDecl> entitiesByFqn) {
        for (ImportDeclaration imp : repo.cu().getImports()) {
            if (!imp.isAsterisk() && !imp.isStatic() && imp.getNameAsString().endsWith("." + repo.entitySimple())) {
                EntityDecl e = entitiesByFqn.get(imp.getNameAsString());
                if (e != null) {
                    return e;
                }
            }
        }
        EntityDecl fallback = null;
        for (EntityDecl e : entitiesByFqn.values()) {
            if (simpleName(e.ir().type).equals(repo.entitySimple())) {
                if (e.ir().module.equals(repo.module())) {
                    return e;
                }
                if ("ts-common".equals(e.ir().module)) {
                    fallback = e;
                }
            }
        }
        return fallback;
    }

    /** Имя поля-репозитория, на котором сделан вызов: repo.find(...) или this.repo.find(...). */
    private static String repositoryFieldOf(MethodCallExpr call) {
        if (call.getScope().isEmpty()) {
            return null;
        }
        Expression scope = call.getScope().get();
        if (scope instanceof NameExpr n) {
            return n.getNameAsString();
        }
        if (scope instanceof FieldAccessExpr f && f.getScope() instanceof ThisExpr) {
            return f.getNameAsString();
        }
        return null;
    }

    private static EntityReportIR.RepositoryCall describeCall(SourceFile sf, MethodCallExpr call, RepoInfo repo, EntityDecl entity) {
        EntityReportIR.RepositoryCall rc = new EntityReportIR.RepositoryCall();
        rc.file = sf.relFile();
        rc.line = call.getName().getBegin().map(p -> p.line).orElse(0);
        rc.col = AstAnalyzer.skeletonCol(call.getName());
        rc.callee = call.getNameAsString();
        rc.repository = repo.name();
        rc.entity = entity == null ? null : entity.ir().type;
        rc.operation = operationOf(rc.callee, repo.modifying());

        if ("READ".equals(rc.operation)) {
            String[] exp = ResultExpectation.analyze(call);
            rc.expects = exp[0];
            rc.expectsReason = exp[1];
        }
        if ("SAVE".equals(rc.operation) && entity != null) {
            idAssigned(call, entity, rc);
        }
        return rc;
    }

    static String operationOf(String callee, Set<String> modifying) {
        if (modifying.contains(callee)) return "MODIFY";
        if (callee.startsWith("save")) return "SAVE";
        if (callee.startsWith("delete") || callee.startsWith("remove")) return "DELETE";
        if (callee.startsWith("exists")) return "EXISTS";
        if (callee.startsWith("count")) return "COUNT";
        return "READ";
    }

    /**
     * Задан ли id сущности до save. Spring Data вызывает persist для сущности с id == null
     * и merge для остальных; merge загружает строку и создаёт экземпляр конструктором без аргументов.
     */
    private static void idAssigned(MethodCallExpr save, EntityDecl entity, EntityReportIR.RepositoryCall rc) {
        String idField = entity.ir().idField;
        if (idField == null || save.getArguments().size() != 1) {
            return;
        }
        Expression arg = save.getArgument(0);
        Expression init = arg;
        String var = null;
        if (arg instanceof NameExpr n) {
            var = n.getNameAsString();
            init = initializerOf(save, var);
        }

        String setter = "set" + Character.toUpperCase(idField.charAt(0)) + idField.substring(1);
        if (var != null) {
            for (MethodCallExpr c : enclosingBody(save).findAll(MethodCallExpr.class)) {
                if (c.getNameAsString().equals(setter) && before(c, save) && c.getScope().isPresent()
                        && c.getScope().get().toString().equals(var)) {
                    mark(rc, true, "line " + line(c) + ": " + c);
                    return;
                }
            }
        }
        if (init instanceof ObjectCreationExpr oce && simpleName(entity.ir().type).equals(baseName(oce.getType().asString()))) {
            if (oce.getArguments().isEmpty()) {
                mark(rc, entity.ir().ctorAssignsId, entity.ir().ctorAssignsId ? "no-arg ctor assigns " + idField : "no-arg ctor leaves " + idField + " null");
                return;
            }
            Boolean byArgs = idFromConstructorArgs(entity, oce);
            if (byArgs != null) {
                mark(rc, byArgs, "line " + line(oce) + ": " + oce);
            }
            return;
        }
        if (init instanceof MethodCallExpr mc && mc.getNameAsString().equals("build")) {
            boolean setsId = mc.findAll(MethodCallExpr.class).stream().anyMatch(c -> c.getNameAsString().equals(idField));
            mark(rc, setsId, "builder " + (setsId ? "sets " : "omits ") + idField);
        }
    }

    private static void mark(EntityReportIR.RepositoryCall rc, boolean value, String reason) {
        rc.idAssigned = value;
        rc.idAssignedReason = reason;
    }

    /** Аргумент конструктора с параметрами, который попадает в поле id (явный конструктор или @AllArgsConstructor). */
    private static Boolean idFromConstructorArgs(EntityDecl entity, ObjectCreationExpr oce) {
        String idField = entity.ir().idField;
        int n = oce.getArguments().size();
        for (ConstructorDeclaration cd : entity.cid().getConstructors()) {
            if (cd.getParameters().size() != n) {
                continue;
            }
            for (AssignExpr a : cd.getBody().findAll(AssignExpr.class)) {
                Expression t = a.getTarget();
                boolean toId = (t instanceof FieldAccessExpr f && f.getNameAsString().equals(idField))
                        || (t instanceof NameExpr ne && ne.getNameAsString().equals(idField));
                if (toId && a.getValue() instanceof NameExpr v) {
                    for (int i = 0; i < n; i++) {
                        if (cd.getParameter(i).getNameAsString().equals(v.getNameAsString())) {
                            return !(oce.getArgument(i) instanceof NullLiteralExpr);
                        }
                    }
                }
            }
            return null;
        }
        if (entity.cid().isAnnotationPresent("AllArgsConstructor")) {
            List<String> fields = new ArrayList<>();
            for (FieldDeclaration fd : entity.cid().getFields()) {
                if (!fd.isStatic()) {
                    fd.getVariables().forEach(v -> fields.add(v.getNameAsString()));
                }
            }
            int idx = fields.indexOf(idField);
            if (fields.size() == n && idx >= 0) {
                return !(oce.getArgument(idx) instanceof NullLiteralExpr);
            }
        }
        return null;
    }

    /** Инициализатор локальной переменной (объявление или последнее присваивание до вызова). */
    private static Expression initializerOf(Node at, String var) {
        Node body = enclosingBody(at);
        Expression result = null;
        for (VariableDeclarator vd : body.findAll(VariableDeclarator.class)) {
            if (vd.getNameAsString().equals(var) && vd.getInitializer().isPresent() && before(vd, at)) {
                result = vd.getInitializer().get();
            }
        }
        for (AssignExpr a : body.findAll(AssignExpr.class)) {
            if (a.getTarget() instanceof NameExpr n && n.getNameAsString().equals(var) && before(a, at)
                    && (result == null || before(result, a))) {
                result = a.getValue();
            }
        }
        return result;
    }

    static Node enclosingBody(Node n) {
        Optional<Node> decl = n.findAncestor(MethodDeclaration.class).map(d -> (Node) d)
                .or(() -> n.findAncestor(ConstructorDeclaration.class).map(d -> (Node) d));
        return decl.orElseGet(n::findRootNode);
    }

    static boolean before(Node a, Node b) {
        return a.getBegin().isPresent() && b.getBegin().isPresent() && a.getBegin().get().isBefore(b.getBegin().get());
    }

    static int line(Node n) {
        return n.getBegin().map(p -> p.line).orElse(0);
    }

    private static boolean isCollection(Type t) {
        return COLLECTION_TYPES.contains(baseName(t.asString())) || t.isArrayType();
    }

    /** Простое имя без пакета и обобщений: "java.util.List<String>" -> "List". */
    static String baseName(String type) {
        String t = type;
        int g = t.indexOf('<');
        if (g >= 0) t = t.substring(0, g);
        t = t.trim();
        int d = t.lastIndexOf('.');
        return d >= 0 ? t.substring(d + 1) : t;
    }

    static String simpleName(String fqn) {
        String s = fqn.substring(fqn.lastIndexOf('.') + 1);
        return s.substring(s.lastIndexOf('$') + 1);
    }
}
