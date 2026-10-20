package com.v39a;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.TryStmt;
import com.v39a.enumres.EnumResolver;
import com.v39a.model.EnumConstantIR;
import com.v39a.parser.AstUtils;
import com.v39a.parser.TypeIndex;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

public class ArchparseTest {

    @Test
    public void testBlockScopedVariableLookup() {
        CompilationUnit cu = StaticJavaParser.parse(
                "package test;\n" +
                "public class Scopes {\n" +
                "    public void run() {\n" +
                "        {\n" +
                "            String x = \"a\";\n" +
                "            System.out.println(x);\n" +
                "        }\n" +
                "        {\n" +
                "            Integer x = 123;\n" +
                "            System.out.println(x);\n" +
                "        }\n" +
                "    }\n" +
                "}"
        );

        ClassOrInterfaceDeclaration cid = cu.findFirst(ClassOrInterfaceDeclaration.class).orElseThrow();
        TypeIndex index = new TypeIndex(cu, cid);

        MethodDeclaration md = cid.getMethodsByName("run").get(0);
        List<MethodCallExpr> calls = md.findAll(MethodCallExpr.class);

        // Первый вызов в блоке String x
        String typeFirst = index.resolveVariableType(calls.get(0), "x");
        assertEquals("String", typeFirst);

        // Второй вызов в блоке Integer x
        String typeSecond = index.resolveVariableType(calls.get(1), "x");
        assertEquals("Integer", typeSecond);
    }

    @Test
    public void testColumnIsUtf8ByteOffset() throws Exception {
        Path file = Files.createTempFile("Utf8Col", ".java");
        Files.writeString(file,
                "public class Utf8Col {\n" +
                "    void f() {\n" +
                "        String s = \"жж\"; g();\n" +
                "    }\n" +
                "    void g() {}\n" +
                "}\n", StandardCharsets.UTF_8);
        CompilationUnit cu = StaticJavaParser.parse(file);
        ClassOrInterfaceDeclaration cid = cu.findFirst(ClassOrInterfaceDeclaration.class).orElseThrow();
        MethodDeclaration md = cid.getMethodsByName("f").get(0);
        MethodCallExpr call = md.findAll(MethodCallExpr.class).get(0);

        // g() стоит на 26-м символе, но на 28-м байте: каждая "ж" занимает 2 байта UTF-8
        int col = AstUtils.skeletonCol(call.getName());
        assertEquals(28, col);
        Files.deleteIfExists(file);
    }

    @Test
    public void testAstUtilsIds() {
        CompilationUnit cu = StaticJavaParser.parse(
                "package test;\n" +
                "import java.util.List;\n" +
                "public class TestClass {\n" +
                "    void f(List<String> items) {\n" +
                "        if (items.isEmpty()) return;\n" +
                "        for (String item : items) {}\n" +
                "        try {\n" +
                "            int x = 1;\n" +
                "        } catch (Exception e) {}\n" +
                "    }\n" +
                "}\n"
        );
        IfStmt ifStmt = cu.findFirst(IfStmt.class).orElseThrow();
        assertEquals("b5", AstUtils.branchId(ifStmt));

        ForEachStmt forEachStmt = cu.findFirst(ForEachStmt.class).orElseThrow();
        assertEquals("f6:items", AstUtils.loopId(forEachStmt));

        TryStmt tryStmt = cu.findFirst(TryStmt.class).orElseThrow();
        assertEquals("t7", AstUtils.tryId(tryStmt));
    }

    @Test
    public void testEnumResolverDynamic() {
        CompilationUnit cu = StaticJavaParser.parse(
                "package edu.fudan.common.entity;\n" +
                "public class DummyOrder {\n" +
                "    void check() {\n" +
                "        int status = OrderStatus.PAID.getCode();\n" +
                "        int seat = SeatClass.FIRSTCLASS.getCode();\n" +
                "    }\n" +
                "}\n"
        );
        List<MethodCallExpr> calls = cu.findAll(MethodCallExpr.class);
        assertEquals(2, calls.size());

        EnumConstantIR statusConst = EnumResolver.resolveCall(calls.get(0), cu);
        assertNotNull(statusConst, "OrderStatus.PAID call must resolve to EnumConstantIR");
        assertEquals("edu.fudan.common.entity.OrderStatus", statusConst.getType());
        assertEquals("PAID", statusConst.getConstant());

        EnumConstantIR seatConst = EnumResolver.resolveCall(calls.get(1), cu);
        assertNotNull(seatConst, "SeatClass.FIRSTCLASS call must resolve to EnumConstantIR");
        assertEquals("edu.fudan.common.entity.SeatClass", seatConst.getType());
        assertEquals("FIRSTCLASS", seatConst.getConstant());

        assertTrue(EnumResolver.isKnownEnumConstant("edu.fudan.common.entity.OrderStatus", "NOTPAID"));
        assertTrue(EnumResolver.isKnownEnumConstant("edu.fudan.common.entity.SeatClass", "BUSINESS"));
        assertFalse(EnumResolver.isKnownEnumConstant("edu.fudan.common.entity.OrderStatus", "NONEXISTENT"));
    }
}
