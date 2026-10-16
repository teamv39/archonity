package com.v39a;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.v39a.config.TargetMethod;
import com.v39a.model.CallIR;
import com.v39a.model.MethodIR;
import com.v39a.parser.AstAnalyzer;
import com.v39a.parser.TypeIndex;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

public class ArchparseTest {

    private Path resolveTargetPath(String relative) {
        String[] prefixes = {
                "../hackaton/tt-challenge/targets/trainticket/",
                "hackaton/tt-challenge/targets/trainticket/",
                "../data/train-ticket/",
                "data/train-ticket/"
        };
        for (String prefix : prefixes) {
            Path p = Paths.get(prefix + relative);
            if (p.toFile().exists()) {
                return p;
            }
        }
        return null;
    }

    @Test
    public void testRealCancelOrderAnalysis() throws Exception {
        Path cancelPath = resolveTargetPath("ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java");
        assertNotNull(cancelPath, "CancelServiceImpl.java must exist in targets");

        CompilationUnit cu = StaticJavaParser.parse(cancelPath);
        ClassOrInterfaceDeclaration cid = cu.findFirst(ClassOrInterfaceDeclaration.class).orElseThrow();
        TypeIndex typeIndex = new TypeIndex(cu, cid);

        TargetMethod target = new TargetMethod(
                "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
                "ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java",
                "cancelOrder",
                "String", "String", "HttpHeaders"
        );

        MethodDeclaration md = cid.getMethodsByName("cancelOrder").get(0);
        MethodIR ir = AstAnalyzer.analyze(target, md, cu, typeIndex);

        assertNotNull(ir);

        // 1. Проверяем точное число вызовов (83 вызова)
        assertEquals(83, ir.getCalls().size(), "cancelOrder must have exactly 83 calls");

        // 2. Проверяем 6 вызовов enum_constant (OrderStatus.NOTPAID, PAID, CHANGE для high-speed и regular)
        List<CallIR> enumCalls = ir.getCalls().stream()
                .filter(c -> c.getEnumConstant() != null)
                .collect(Collectors.toList());
        assertEquals(6, enumCalls.size(), "cancelOrder must contain exactly 6 enum constant calls");

        for (CallIR ec : enumCalls) {
            assertEquals("edu.fudan.common.entity.OrderStatus", ec.getEnumConstant().getType());
            assertTrue(List.of("NOTPAID", "PAID", "CHANGE").contains(ec.getEnumConstant().getConstant()));
            assertEquals("getCode", ec.getCallee());
            assertEquals("ENUM", ec.getKind());
        }

        // 3. Проверяем Guard (условия исполнения)
        // Первые вызовы (до if) выполняются безусловно
        CallIR firstCall = ir.getCalls().get(0);
        assertEquals("getOrderByIdFromOrder", firstCall.getCallee());
        assertTrue(firstCall.getGuard().isEmpty(), "First call before any if must have empty guard");
        assertEquals("SAME_CLASS", firstCall.getKind());

        // Вызовы внутри then (high-speed) должны содержать условие orderResult.getStatus() == 1
        CallIR cancelFromOrderCall = ir.getCalls().stream()
                .filter(c -> "cancelFromOrder".equals(c.getCallee()))
                .findFirst()
                .orElseThrow();
        assertTrue(cancelFromOrderCall.getGuard().stream().anyMatch(g -> g.equals("b49:then")));

        // Вызов getOrderByIdFromOrderOther (regular) должен содержать отрицание !(orderResult.getStatus() == 1)
        CallIR otherCall = ir.getCalls().stream()
                .filter(c -> "getOrderByIdFromOrderOther".equals(c.getCallee()))
                .findFirst()
                .orElseThrow();
        assertTrue(otherCall.getGuard().stream().anyMatch(g -> g.equals("b49:else")));

        // 4. Проверяем наличие разных категорий kind
        assertTrue(ir.getCalls().stream().anyMatch(c -> "CONSTRUCTOR".equals(c.getKind())));
        assertTrue(ir.getCalls().stream().anyMatch(c -> "SAME_CLASS".equals(c.getKind())));
        assertTrue(ir.getCalls().stream().anyMatch(c -> "OTHER".equals(c.getKind())));
        assertTrue(ir.getCalls().stream().anyMatch(c -> "ENUM".equals(c.getKind())));
    }

    @Test
    public void testInsidePaymentUnsupportedLoops() throws Exception {
        Path payPath = resolveTargetPath("ts-inside-payment-service/src/main/java/inside_payment/service/InsidePaymentServiceImpl.java");
        assertNotNull(payPath, "InsidePaymentServiceImpl.java must exist in targets");

        CompilationUnit cu = StaticJavaParser.parse(payPath);
        ClassOrInterfaceDeclaration cid = cu.findFirst(ClassOrInterfaceDeclaration.class).orElseThrow();
        TypeIndex typeIndex = new TypeIndex(cu, cid);

        TargetMethod target = new TargetMethod(
                "method:ts-inside-payment-service:inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
                "ts-inside-payment-service/src/main/java/inside_payment/service/InsidePaymentServiceImpl.java",
                "pay",
                "PaymentInfo", "HttpHeaders"
        );

        MethodDeclaration md = cid.getMethodsByName("pay").get(0);
        MethodIR ir = AstAnalyzer.analyze(target, md, cu, typeIndex);

        assertNotNull(ir);
        assertEquals(80, ir.getCalls().size(), "pay must have 80 calls");

        // Проверяем честность unsupported: циклы while для R17 должны быть зафиксированы
        assertFalse(ir.getUnsupported().isEmpty(), "unsupported must not be empty for pay()");
        assertTrue(ir.getUnsupported().stream().anyMatch(u -> u.contains("while loop not modeled (R17)")),
                "unsupported must flag while loops for R17");
    }

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
        List<com.github.javaparser.ast.expr.MethodCallExpr> calls = md.findAll(com.github.javaparser.ast.expr.MethodCallExpr.class);

        // Первый вызов в блоке String x
        String typeFirst = index.resolveVariableType(calls.get(0), "x");
        assertEquals("String", typeFirst);

        // Второй вызов в блоке Integer x
        String typeSecond = index.resolveVariableType(calls.get(1), "x");
        assertEquals("Integer", typeSecond);
    }

    @Test
    public void testEarlyExitPerArmAndGuardIds() {
        CompilationUnit cu = StaticJavaParser.parse("package test;\n" +
                "public class Dummy {\n" +
                "    int f(int a) {\n" +
                "        if (a > 0) {\n" +
                "            g();\n" +
                "        } else if (a == 0) {\n" +
                "            return 0;\n" +
                "        } else {\n" +
                "            return -1;\n" +
                "        }\n" +
                "        return 1;\n" +
                "    }\n" +
                "    void g() {}\n" +
                "}");
        ClassOrInterfaceDeclaration cid = cu.findFirst(ClassOrInterfaceDeclaration.class).get();
        MethodDeclaration md = cid.getMethods().get(0);
        TargetMethod target = new TargetMethod("method:dummy:Dummy#f(int)", "Dummy.java", "f", "int");
        MethodIR ir = AstAnalyzer.analyze(target, md, cu, new TypeIndex(cu, cid));

        // then не выходит, а else (цепочка else-if, где все плечи return) выходит
        assertEquals("b4", ir.getBranches().get(0).getId());
        assertFalse(ir.getBranches().get(0).getEarlyExit().isThenArm());
        assertTrue(ir.getBranches().get(0).getEarlyExit().isElseArm());
        assertEquals(List.of("b4:else"), ir.getBranches().get(1).getGuard());
        assertEquals(List.of("b4:then"), ir.getCalls().get(0).getGuard());
    }
}
