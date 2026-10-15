package com.v39a;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;

import java.util.ArrayList;
import java.util.List;

public class Parser {

    private static final List<Endpoint> allEndpoints = new ArrayList<>();

    public static List<Endpoint> getAllEndpoints(){
        return allEndpoints;
    }

    static VoidVisitorAdapter<List<Endpoint>> visitor = new VoidVisitorAdapter<>() {
        @Override
        public void visit(MethodDeclaration md, List<Endpoint> arg) {
            super.visit(md, arg);
            md.getAnnotationByName("PostMapping").ifPresent(ann -> {
                System.out.println("Найден POST endpoint: " + md.getNameAsString()
                        + " с аннотацией " + ann);
                ClassOrInterfaceDeclaration parent = (md.findAncestor(ClassOrInterfaceDeclaration.class).orElse(new ClassOrInterfaceDeclaration()));
                arg.add(new Endpoint(parent.getNameAsString(), md.getNameAsString(), ann.toString()));
            });

        }

        @Override
        public void visit(MethodCallExpr mc, List<Endpoint> arg) {
            super.visit(mc, arg);

            if (mc.getNameAsString().equals("postForObject") || mc.getNameAsString().equals("getForObject")) {
                System.out.println("Вызов RestTemplate: " + mc.getNameAsString()
                        + " Целевой URL: " + mc.getArgument(0));
                ClassOrInterfaceDeclaration parent = mc.findAncestor(ClassOrInterfaceDeclaration.class).orElse(new ClassOrInterfaceDeclaration());
                arg.add(new Endpoint(parent.getNameAsString(), mc.getNameAsString(), mc.getArgument(0).toString()));
            }
        }
    };


    public static void parse(CompilationUnit cu) {
        cu.accept(visitor, allEndpoints);
    }
}

