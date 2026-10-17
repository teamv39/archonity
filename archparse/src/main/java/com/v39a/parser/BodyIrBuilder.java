package com.v39a.parser;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.*;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.stmt.*;
import com.v39a.skeleton.SkeletonGraph;

import java.util.*;

/**
 * IR тела одного метода по контракту README, раздел 3.6: дерево операторов и выражений,
 * вызовы привязаны к call_site скелета, константы enum и static final вычислены.
 */
public class BodyIrBuilder {

    private static final JsonNodeFactory F = JsonNodeFactory.instance;

    private final SkeletonGraph skeleton;
    private final ProjectIndex project;
    private final CompilationUnit cu;
    private final String module;
    private final String file;
    private final SkeletonGraph.MethodNode method;
    private final Set<String> params = new HashSet<>();
    private final Deque<Set<String>> locals = new ArrayDeque<>();
    private final Set<String> fields = new HashSet<>();
    private final List<String> enclosingTypes = new ArrayList<>(); // FQN объемлющих типов, изнутри наружу

    /** Позиции call_site, которые встретились в теле (для проверки покрытия). */
    private final List<String> callSitesSeen = new ArrayList<>();
    private int irCalls;

    public BodyIrBuilder(SkeletonGraph skeleton, ProjectIndex project, CompilationUnit cu, String module,
                         String file, SkeletonGraph.MethodNode method, CallableDeclaration<?> decl) {
        this.skeleton = skeleton;
        this.project = project;
        this.cu = cu;
        this.module = module;
        this.file = file;
        this.method = method;
        for (Parameter p : decl.getParameters()) {
            params.add(p.getNameAsString());
        }
        String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
        Node cur = decl.getParentNode().orElse(null);
        while (cur != null) {
            if (cur instanceof TypeDeclaration<?> td) {
                td.getFields().forEach(fd -> fd.getVariables().forEach(v -> fields.add(v.getNameAsString())));
                if (td instanceof EnumDeclaration ed) {
                    ed.getEntries().forEach(c -> fields.add(c.getNameAsString()));
                }
                enclosingTypes.add(ProjectIndex.binaryName(pkg, td));
            } else if (cur instanceof ObjectCreationExpr oce && oce.getAnonymousClassBody().isPresent()) {
                for (BodyDeclaration<?> b : oce.getAnonymousClassBody().get()) {
                    if (b instanceof FieldDeclaration fd) {
                        fd.getVariables().forEach(v -> fields.add(v.getNameAsString()));
                    }
                }
            }
            cur = cur.getParentNode().orElse(null);
        }
    }

    public List<String> callSitesSeen() {
        return callSitesSeen;
    }

    public int irCalls() {
        return irCalls;
    }

    public ObjectNode build(CallableDeclaration<?> decl, BlockStmt body) {
        ObjectNode out = F.objectNode();
        out.put("file", file);
        out.put("line", method.line());
        out.put("end", method.end());
        ArrayNode ps = out.putArray("params");
        for (Parameter p : decl.getParameters()) {
            ps.addObject().put("name", p.getNameAsString()).put("type", p.getType().asString());
        }
        out.set("body", block(body));
        return out;
    }

    // ------------------------------------------------------------------
    // Операторы
    // ------------------------------------------------------------------

    private ArrayNode block(Statement s) {
        ArrayNode out = F.arrayNode();
        locals.push(new HashSet<>());
        if (s instanceof BlockStmt b) {
            for (Statement st : b.getStatements()) {
                stmt(st, out);
            }
        } else if (s != null) {
            stmt(s, out);
        }
        locals.pop();
        return out;
    }

    private ObjectNode op(String op, Node n) {
        ObjectNode o = F.objectNode();
        o.put("op", op);
        o.put("line", line(n));
        return o;
    }

    private void stmt(Statement s, ArrayNode out) {
        if (s instanceof ExpressionStmt es) {
            Expression e = es.getExpression();
            if (e instanceof VariableDeclarationExpr vde) {
                declarations(vde, out);
            } else if (e instanceof AssignExpr ae) {
                ObjectNode o = op("assign", s);
                o.set("target", expr(ae.getTarget()));
                o.put("operator", ae.getOperator().asString());
                o.set("expr", expr(ae.getValue()));
                out.add(o);
            } else {
                out.add(op("expr", s).set("expr", expr(e)));
            }
        } else if (s instanceof IfStmt is) {
            ObjectNode o = op("if", s);
            o.put("id", AstAnalyzer.branchId(is));
            o.set("cond", expr(is.getCondition()));
            o.set("then", block(is.getThenStmt()));
            o.set("else", is.getElseStmt().map(this::block).orElse(F.arrayNode()));
            out.add(o);
        } else if (s instanceof SwitchStmt ss) {
            ObjectNode o = op("switch", s);
            o.set("selector", expr(ss.getSelector()));
            ArrayNode cases = o.putArray("cases");
            locals.push(new HashSet<>());
            for (SwitchEntry se : ss.getEntries()) {
                ObjectNode c = cases.addObject();
                ArrayNode labels = c.putArray("labels");
                for (Expression l : se.getLabels()) {
                    labels.add(caseLabel(l));
                }
                ArrayNode body = c.putArray("body");
                for (Statement st : se.getStatements()) {
                    stmt(st, body);
                }
            }
            locals.pop();
            out.add(o);
        } else if (s instanceof WhileStmt ws) {
            out.add(op("while", s).<ObjectNode>set("cond", expr(ws.getCondition())).set("body", block(ws.getBody())));
        } else if (s instanceof DoStmt ds) {
            ObjectNode o = op("do", s);
            o.set("body", block(ds.getBody()));
            o.set("cond", expr(ds.getCondition()));
            out.add(o);
        } else if (s instanceof ForStmt fs) {
            ObjectNode o = op("for", s);
            locals.push(new HashSet<>());
            ArrayNode init = o.putArray("init");
            for (Expression e : fs.getInitialization()) {
                if (e instanceof VariableDeclarationExpr vde) {
                    declarations(vde, init);
                } else {
                    init.add(op("expr", e).set("expr", expr(e)));
                }
            }
            o.set("cond", fs.getCompare().map(this::expr).orElse(null));
            ArrayNode upd = o.putArray("update");
            fs.getUpdate().forEach(e -> upd.add(expr(e)));
            o.set("body", block(fs.getBody()));
            locals.pop();
            out.add(o);
        } else if (s instanceof ForEachStmt fe) {
            ObjectNode o = op("foreach", s);
            o.put("id", AstAnalyzer.loopId(fe));
            VariableDeclarator v = fe.getVariable().getVariable(0);
            o.put("var", v.getNameAsString());
            o.put("var_type", v.getType().asString());
            o.set("iter", expr(fe.getIterable()));
            locals.push(new HashSet<>(Set.of(v.getNameAsString())));
            o.set("body", block(fe.getBody()));
            locals.pop();
            out.add(o);
        } else if (s instanceof TryStmt ts) {
            ObjectNode o = op("try", s);
            o.put("id", AstAnalyzer.tryId(ts));
            locals.push(new HashSet<>());
            ArrayNode res = o.putArray("resources");
            for (Expression r : ts.getResources()) {
                if (r instanceof VariableDeclarationExpr vde) {
                    declarations(vde, res);
                } else {
                    res.add(op("expr", r).set("expr", expr(r)));
                }
            }
            o.set("body", block(ts.getTryBlock()));
            locals.pop();
            ArrayNode catches = o.putArray("catches");
            for (CatchClause cc : ts.getCatchClauses()) {
                ObjectNode c = catches.addObject();
                ArrayNode types = c.putArray("types");
                if (cc.getParameter().getType().isUnionType()) {
                    cc.getParameter().getType().asUnionType().getElements().forEach(t -> types.add(t.asString()));
                } else {
                    types.add(cc.getParameter().getType().asString());
                }
                c.put("var", cc.getParameter().getNameAsString());
                locals.push(new HashSet<>(Set.of(cc.getParameter().getNameAsString())));
                c.set("body", block(cc.getBody()));
                locals.pop();
            }
            o.set("finally", ts.getFinallyBlock().map(this::block).orElse(null));
            out.add(o);
        } else if (s instanceof ReturnStmt rs) {
            ObjectNode o = op("return", s);
            rs.getExpression().ifPresent(e -> o.set("expr", expr(e)));
            out.add(o);
        } else if (s instanceof ThrowStmt ts) {
            out.add(op("throw", s).set("expr", expr(ts.getExpression())));
        } else if (s instanceof BreakStmt bs) {
            ObjectNode o = op("break", s);
            bs.getLabel().ifPresent(l -> o.put("label", l.asString()));
            out.add(o);
        } else if (s instanceof ContinueStmt cs) {
            ObjectNode o = op("continue", s);
            cs.getLabel().ifPresent(l -> o.put("label", l.asString()));
            out.add(o);
        } else if (s instanceof BlockStmt) {
            out.add(op("block", s).set("body", block(s)));
        } else if (s instanceof SynchronizedStmt ss) {
            ObjectNode o = op("block", s);
            o.set("lock", expr(ss.getExpression()));
            o.set("body", block(ss.getBody()));
            out.add(o);
        } else if (s instanceof LabeledStmt ls) {
            ObjectNode o = op("block", s);
            o.put("label", ls.getLabel().asString());
            o.set("body", block(ls.getStatement()));
            out.add(o);
        } else if (s instanceof ExplicitConstructorInvocationStmt eci) {
            ObjectNode call = F.objectNode();
            putCallId(call, file, line(eci), AstAnalyzer.skeletonCol(eci), null);
            call.put("callee", eci.isThis() ? "this" : "super");
            call.putNull("recv");
            ArrayNode args = call.putArray("args");
            eci.getArguments().forEach(a -> args.add(expr(a)));
            out.add(op("expr", s).set("expr", call));
        } else if (s instanceof EmptyStmt) {
            // пустой оператор не несёт исполнения
        } else {
            out.add(op("unsupported", s).put("text", firstLine(s)));
        }
    }

    private void declarations(VariableDeclarationExpr vde, ArrayNode out) {
        for (VariableDeclarator vd : vde.getVariables()) {
            ObjectNode o = op("assign", vd);
            o.set("target", F.objectNode().put("name", vd.getNameAsString()).put("ref", "local"));
            o.put("decl", vd.getType().asString());
            o.put("operator", "=");
            vd.getInitializer().ifPresent(init -> o.set("expr", expr(init)));
            declare(vd.getNameAsString());
            out.add(o);
        }
    }

    private void declare(String name) {
        if (locals.isEmpty()) {
            locals.push(new HashSet<>());
        }
        locals.peek().add(name);
    }

    private boolean isLocal(String name) {
        for (Set<String> s : locals) {
            if (s.contains(name)) {
                return true;
            }
        }
        return false;
    }

    private JsonNode caseLabel(Expression l) {
        if (l instanceof NameExpr n && !isLocal(n.getNameAsString()) && !params.contains(n.getNameAsString())) {
            String enumFqn = project.uniqueEnumOf(n.getNameAsString());
            if (enumFqn != null) {
                return enumNode(enumFqn, n.getNameAsString());
            }
        }
        return expr(l);
    }

    // ------------------------------------------------------------------
    // Выражения
    // ------------------------------------------------------------------

    JsonNode expr(Expression e) {
        if (e == null) {
            return F.nullNode();
        }
        if (e instanceof EnclosedExpr en) {
            return expr(en.getInner());
        }
        if (e instanceof LiteralExpr le) {
            return literal(le);
        }
        if (e instanceof NameExpr n) {
            return name(n);
        }
        if (e instanceof FieldAccessExpr fa) {
            return fieldAccess(fa);
        }
        if (e instanceof MethodCallExpr mc) {
            return methodCall(mc);
        }
        if (e instanceof ObjectCreationExpr oce) {
            return objectCreation(oce);
        }
        if (e instanceof BinaryExpr be) {
            ObjectNode o = F.objectNode();
            o.put("bin", be.getOperator().asString());
            o.set("l", expr(be.getLeft()));
            o.set("r", expr(be.getRight()));
            return o;
        }
        if (e instanceof UnaryExpr ue) {
            ObjectNode o = F.objectNode();
            o.put("un", unaryOp(ue.getOperator()));
            o.set("e", expr(ue.getExpression()));
            return o;
        }
        if (e instanceof AssignExpr ae) {
            ObjectNode o = F.objectNode();
            o.put("assign", ae.getOperator().asString());
            o.set("target", expr(ae.getTarget()));
            o.set("expr", expr(ae.getValue()));
            return o;
        }
        if (e instanceof ConditionalExpr ce) {
            ObjectNode o = F.objectNode();
            o.set("tern", expr(ce.getCondition()));
            o.set("then", expr(ce.getThenExpr()));
            o.set("else", expr(ce.getElseExpr()));
            return o;
        }
        if (e instanceof CastExpr ce) {
            ObjectNode o = F.objectNode();
            o.put("cast", ce.getType().asString());
            o.set("e", expr(ce.getExpression()));
            return o;
        }
        if (e instanceof InstanceOfExpr ie) {
            ObjectNode o = F.objectNode();
            o.put("instanceof", ie.getType().asString());
            o.set("e", expr(ie.getExpression()));
            return o;
        }
        if (e instanceof ArrayAccessExpr aa) {
            ObjectNode o = F.objectNode();
            o.set("index", expr(aa.getIndex()));
            o.set("of", expr(aa.getName()));
            return o;
        }
        if (e instanceof ArrayCreationExpr ac) {
            ObjectNode o = F.objectNode();
            o.put("new_array", ac.getElementType().asString());
            ArrayNode dims = o.putArray("dims");
            ac.getLevels().forEach(l -> dims.add(l.getDimension().map(this::expr).orElse(F.nullNode())));
            o.set("init", ac.getInitializer().map(this::expr).orElse(null));
            return o;
        }
        if (e instanceof ArrayInitializerExpr ai) {
            ObjectNode o = F.objectNode();
            o.putNull("new_array");
            ArrayNode init = o.putArray("init");
            ai.getValues().forEach(v -> init.add(expr(v)));
            return o;
        }
        if (e instanceof LambdaExpr le) {
            return lambda(le);
        }
        if (e instanceof MethodReferenceExpr mr) {
            ObjectNode o = F.objectNode();
            o.put("method_ref", mr.toString());
            // скелет ставит колонку на имя после "::", у "::new" — на начало выражения
            int col = AstAnalyzer.skeletonCol(mr);
            int line = line(mr);
            if (!"new".equals(mr.getIdentifier()) && mr.getEnd().isPresent()) {
                line = mr.getEnd().get().line;
                col = AstAnalyzer.skeletonCol(mr, line, mr.getEnd().get().column - mr.getIdentifier().length() + 1);
            }
            String cs = skeleton.callSite(file, line, col);
            if (cs != null) {
                callSitesSeen.add(cs);
                o.put("call", cs);
            }
            return o;
        }
        if (e instanceof ThisExpr) {
            return F.objectNode().put("this", true);
        }
        if (e instanceof SuperExpr) {
            return F.objectNode().put("super", true);
        }
        if (e instanceof ClassExpr ce) {
            return F.objectNode().put("class", ce.getType().asString());
        }
        if (e instanceof VariableDeclarationExpr vde) {
            // объявление в позиции выражения (pattern/try): объявляем имена, значения разбираем
            ArrayNode decl = F.arrayNode();
            declarations(vde, decl);
            return F.objectNode().set("decls", decl);
        }
        // страховка: неразобранное выражение; вызовы внутри всё равно привязываем
        ObjectNode o = F.objectNode().put("text", e.toString());
        ArrayNode inner = F.arrayNode();
        e.findAll(MethodCallExpr.class).forEach(mc -> inner.add(methodCall(mc)));
        if (!inner.isEmpty()) {
            o.set("calls", inner);
        }
        return o;
    }

    private static String unaryOp(UnaryExpr.Operator op) {
        return switch (op) {
            case PREFIX_INCREMENT -> "++pre";
            case PREFIX_DECREMENT -> "--pre";
            case POSTFIX_INCREMENT -> "post++";
            case POSTFIX_DECREMENT -> "post--";
            default -> op.asString();
        };
    }

    static JsonNode literal(LiteralExpr le) {
        ObjectNode o = F.objectNode();
        if (le instanceof IntegerLiteralExpr i) {
            o.put("lit", i.asNumber().longValue()).put("type", "int");
        } else if (le instanceof LongLiteralExpr l) {
            o.put("lit", l.asNumber().longValue()).put("type", "long");
        } else if (le instanceof DoubleLiteralExpr d) {
            o.put("lit", d.asDouble()).put("type", "double");
        } else if (le instanceof CharLiteralExpr c) {
            o.put("lit", String.valueOf(c.asChar())).put("type", "char");
        } else if (le instanceof TextBlockLiteralExpr tb) {
            o.put("lit", tb.asString()).put("type", "string");
        } else if (le instanceof StringLiteralExpr s) {
            o.put("lit", s.asString()).put("type", "string");
        } else if (le instanceof BooleanLiteralExpr b) {
            o.put("lit", b.getValue()).put("type", "boolean");
        } else {
            o.putNull("lit").put("type", "null");
        }
        return o;
    }

    private JsonNode constValue(Expression init) {
        if (init instanceof UnaryExpr u) {
            ObjectNode v = (ObjectNode) literal((LiteralExpr) u.getExpression());
            JsonNode lit = v.get("lit");
            if (lit.isIntegralNumber()) {
                v.put("lit", -lit.asLong());
            } else if (lit.isNumber()) {
                v.put("lit", -lit.asDouble());
            }
            return v;
        }
        return literal((LiteralExpr) init);
    }

    private JsonNode name(NameExpr n) {
        String id = n.getNameAsString();
        if (isLocal(id)) {
            return F.objectNode().put("name", id).put("ref", "local");
        }
        if (params.contains(id)) {
            return F.objectNode().put("name", id).put("ref", "param");
        }
        if (fields.contains(id)) {
            for (String t : enclosingTypes) {
                Expression c = project.constant(t, id);
                if (c != null) {
                    return constNode(t + "." + id, c);
                }
                if (project.enumConstant(t, id) != null) {
                    return enumNode(t, id);
                }
            }
            return F.objectNode().put("name", id).put("ref", "field");
        }
        JsonNode st = staticImport(id);
        if (st != null) {
            return st;
        }
        boolean imported = cu.getImports().stream().anyMatch(imp -> imp.isStatic()
                && (imp.isAsterisk() || imp.getNameAsString().endsWith("." + id)));
        String ref = imported ? "static" : Character.isUpperCase(id.charAt(0)) ? "type" : "unknown";
        return F.objectNode().put("name", id).put("ref", ref);
    }

    /** Константа по статическому импорту: enum или static final поле типа проекта. */
    private JsonNode staticImport(String id) {
        for (var imp : cu.getImports()) {
            if (!imp.isStatic()) {
                continue;
            }
            String nm = imp.getNameAsString();
            String typeName = imp.isAsterisk() ? nm : (nm.endsWith("." + id) ? nm.substring(0, nm.length() - id.length() - 1) : null);
            if (typeName == null) {
                continue;
            }
            String simple = typeName.substring(typeName.lastIndexOf('.') + 1);
            String fqn = project.resolveType(simple, cu, module);
            if (fqn == null) {
                continue;
            }
            if (project.enumConstant(fqn, id) != null) {
                return enumNode(fqn, id);
            }
            Expression c = project.constant(fqn, id);
            if (c != null) {
                return constNode(fqn + "." + id, c);
            }
        }
        return null;
    }

    private JsonNode fieldAccess(FieldAccessExpr fa) {
        String typeFqn = typeOf(fa.getScope());
        if (typeFqn != null) {
            if (project.enumConstant(typeFqn, fa.getNameAsString()) != null) {
                return enumNode(typeFqn, fa.getNameAsString());
            }
            Expression c = project.constant(typeFqn, fa.getNameAsString());
            if (c != null) {
                return constNode(typeFqn + "." + fa.getNameAsString(), c);
            }
        }
        ObjectNode o = F.objectNode();
        o.put("field", fa.getNameAsString());
        o.set("of", expr(fa.getScope()));
        return o;
    }

    /** FQN типа проекта, если выражение — имя типа (`OrderStatus`, `edu.fudan.common.entity.OrderStatus`). */
    private String typeOf(Expression scope) {
        if (scope instanceof NameExpr n) {
            String id = n.getNameAsString();
            if (isLocal(id) || params.contains(id) || fields.contains(id) || !Character.isUpperCase(id.charAt(0))) {
                return null;
            }
            return project.resolveType(id, cu, module);
        }
        if (scope instanceof FieldAccessExpr fa && Character.isUpperCase(fa.getNameAsString().charAt(0))) {
            String simple = fa.getNameAsString();
            String fqn = project.resolveType(simple, cu, module);
            return fqn != null && fqn.replace('$', '.').equals(fa.toString()) ? fqn : null;
        }
        return null;
    }

    private ObjectNode enumNode(String fqn, String constant) {
        ObjectNode o = F.objectNode();
        o.put("enum", fqn);
        o.put("constant", constant);
        ArrayNode args = o.putArray("args");
        for (Expression a : project.enumConstant(fqn, constant)) {
            args.add(ProjectIndex.isLiteral(a) ? constValue(a) : F.objectNode().put("text", a.toString()));
        }
        return o;
    }

    private ObjectNode constNode(String qualified, Expression init) {
        ObjectNode o = F.objectNode();
        o.put("const", qualified);
        o.set("value", constValue(init));
        return o;
    }

    private JsonNode methodCall(MethodCallExpr mc) {
        ObjectNode o = F.objectNode();
        JsonNode recv = mc.getScope().map(this::expr).orElse(null);
        String owner = null;
        if (mc.getScope().isEmpty() || mc.getScope().get() instanceof ThisExpr) {
            owner = method.owner();
        } else if (recv != null && recv.has("enum")) {
            owner = recv.get("enum").asText();
        } else if (recv != null && "type".equals(recv.path("ref").asText())) {
            owner = project.resolveType(recv.get("name").asText(), cu, module);
        }
        putCallId(o, file, line(mc.getName()), AstAnalyzer.skeletonCol(mc.getName()),
                owner == null ? null : skeleton.uniqueMethod(owner, mc.getNameAsString(), mc.getArguments().size()));
        o.put("callee", mc.getNameAsString());
        o.set("recv", recv);
        ArrayNode args = o.putArray("args");
        mc.getArguments().forEach(a -> args.add(expr(a)));
        return o;
    }

    private JsonNode objectCreation(ObjectCreationExpr oce) {
        ObjectNode o = F.objectNode();
        o.put("new", oce.getType().asString());
        String cs = skeleton.callSite(file, line(oce), AstAnalyzer.skeletonCol(oce));
        if (cs != null) {
            callSitesSeen.add(cs);
            o.put("call", cs);
        }
        ArrayNode args = o.putArray("args");
        oce.getArguments().forEach(a -> args.add(expr(a)));
        if (oce.getAnonymousClassBody().isPresent()) {
            String anon = skeleton.anonymousType(file, line(oce));
            o.put("anon", anon == null ? "unresolved" : anon);
        }
        return o;
    }

    private void putCallId(ObjectNode o, String file, int line, int col, SkeletonGraph.MethodNode target) {
        String cs = skeleton.callSite(file, line, col);
        if (cs != null) {
            callSitesSeen.add(cs);
            o.put("call", cs);
        } else {
            irCalls++;
            o.put("call", "ircall:" + method.id() + "@" + line + ":" + col);
            if (target != null) {
                o.put("target", target.id());
            }
        }
    }

    private JsonNode lambda(LambdaExpr le) {
        ObjectNode o = F.objectNode();
        ObjectNode inner = o.putObject("lambda");
        inner.put("line", line(le));
        ArrayNode ps = inner.putArray("params");
        Set<String> names = new HashSet<>();
        for (Parameter p : le.getParameters()) {
            ps.add(p.getNameAsString());
            names.add(p.getNameAsString());
        }
        locals.push(names);
        if (le.getBody() instanceof BlockStmt b) {
            inner.set("body", block(b));
        } else if (le.getBody() instanceof ExpressionStmt es) {
            ArrayNode body = F.arrayNode();
            body.add(op("return", es).set("expr", expr(es.getExpression())));
            inner.set("body", body);
        } else {
            inner.set("body", block(le.getBody()));
        }
        locals.pop();
        return o;
    }

    static int line(Node n) {
        return n.getBegin().map(p -> p.line).orElse(0);
    }

    private static String firstLine(Node n) {
        String s = n.toString();
        int i = s.indexOf('\n');
        return i >= 0 ? s.substring(0, i) : s;
    }
}
