package com.v39a;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.v39a.config.TargetMethod;
import com.v39a.config.TargetPool;
import com.v39a.model.MethodIR;
import com.v39a.parser.AstAnalyzer;
import com.v39a.parser.TypeIndex;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;

public class Main {

    public static void main(String[] args) throws IOException {
        String repoRootStr = null;
        String outputPathStr = null;
        String poolType = "initial"; // 1-4 или "all" (1-7)

        for (int i = 0; i < args.length; i++) {
            if ("--targets-dir".equals(args[i]) || "--repo-root".equals(args[i])) {
                if (i + 1 < args.length) repoRootStr = args[++i];
            } else if ("--output".equals(args[i]) || "-o".equals(args[i])) {
                if (i + 1 < args.length) outputPathStr = args[++i];
            } else if ("--pool".equals(args[i])) {
                if (i + 1 < args.length) poolType = args[++i];
            }
        }

        Path targetsDir = resolveTargetsDir(repoRootStr);
        Path outputFile = resolveOutputFile(outputPathStr);

        System.out.println("archparse: Starting method body analysis");
        System.out.println("Targets directory: " + targetsDir.toAbsolutePath());
        System.out.println("Output file: " + outputFile.toAbsolutePath());
        System.out.println("Pool type: " + poolType);

        List<TargetMethod> pool = "all".equalsIgnoreCase(poolType) ? TargetPool.getFullPool() : TargetPool.getInitialPool();
        System.out.println("Target methods count: " + pool.size());

        // Группируем методы по файлам
        Map<String, List<TargetMethod>> fileToTargets = new LinkedHashMap<>();
        for (TargetMethod tm : pool) {
            fileToTargets.computeIfAbsent(tm.relativeFile(), k -> new ArrayList<>()).add(tm);
        }

        List<MethodIR> results = new ArrayList<>();

        for (Map.Entry<String, List<TargetMethod>> entry : fileToTargets.entrySet()) {
            String relFile = entry.getKey();
            List<TargetMethod> targets = entry.getValue();

            Path fullPath = targetsDir.resolve(relFile);
            if (!Files.exists(fullPath)) {
                System.err.println("File not found: " + fullPath);
                continue;
            }

            System.out.println("Parsing file: " + relFile);
            CompilationUnit cu = StaticJavaParser.parse(fullPath);

            Optional<ClassOrInterfaceDeclaration> mainClassOpt = cu.findFirst(ClassOrInterfaceDeclaration.class);
            if (mainClassOpt.isEmpty()) {
                System.err.println("No class found in " + relFile);
                continue;
            }

            ClassOrInterfaceDeclaration cid = mainClassOpt.get();

            // Индекс типов
            TypeIndex typeIndex = new TypeIndex(cu, cid);

            // Анализ каждого метода из пула
            for (TargetMethod target : targets) {
                MethodDeclaration matchedMd = findMethod(cid, target);
                if (matchedMd == null) {
                    System.err.println("Method not found in AST: " + target.methodName() + " (" + target.methodId() + ")");
                    continue;
                }

                MethodIR methodIR = AstAnalyzer.analyze(target, matchedMd, cu, typeIndex);
                results.add(methodIR);
                System.out.printf("  [OK] %s: %d branches, %d calls%n",
                        target.methodName(), methodIR.getBranches().size(), methodIR.getCalls().size());
            }
        }

        // Сериализация в JSON
        if (outputFile.getParent() != null) {
            Files.createDirectories(outputFile.getParent());
        }

        ObjectMapper mapper = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);
        mapper.writeValue(outputFile.toFile(), results);

        System.out.println("Finished! Saved " + results.size() + " method IRs to " + outputFile.toAbsolutePath());
    }

    private static MethodDeclaration findMethod(ClassOrInterfaceDeclaration cid, TargetMethod target) {
        for (MethodDeclaration md : cid.getMethods()) {
            if (target.matches(md.getNameAsString(), md.getParameters().size())) {
                boolean paramsMatch = true;
                for (int i = 0; i < target.paramTypes().size(); i++) {
                    String expectedType = target.paramTypes().get(i);
                    String actualType = md.getParameter(i).getType().asString();
                    if (!matchesType(actualType, expectedType)) {
                        paramsMatch = false;
                        break;
                    }
                }
                if (paramsMatch) {
                    return md;
                }
            }
        }
        return null;
    }

    private static boolean matchesType(String actualType, String expectedType) {
        String actualSimple = getSimpleTypeName(actualType);
        String expectedSimple = getSimpleTypeName(expectedType);
        return actualSimple.equals(expectedSimple);
    }

    private static String getSimpleTypeName(String typeStr) {
        if (typeStr == null) return "";
        int genIdx = typeStr.indexOf('<');
        if (genIdx > 0) {
            typeStr = typeStr.substring(0, genIdx);
        }
        typeStr = typeStr.trim();
        int dotIdx = typeStr.lastIndexOf('.');
        if (dotIdx >= 0) {
            typeStr = typeStr.substring(dotIdx + 1);
        }
        return typeStr.trim();
    }

    private static Path resolveTargetsDir(String explicit) {
        if (explicit != null) {
            return Paths.get(explicit);
        }

        // Кандидаты для поиска targets/trainticket
        String[] candidates = {
                "hackaton/tt-challenge/targets/trainticket",
                "../hackaton/tt-challenge/targets/trainticket",
                "data/train-ticket",
                "../data/train-ticket"
        };

        for (String cand : candidates) {
            Path p = Paths.get(cand);
            if (Files.exists(p)) {
                return p;
            }
        }

        return Paths.get("hackaton/tt-challenge/targets/trainticket");
    }

    private static Path resolveOutputFile(String explicit) {
        if (explicit != null) {
            return Paths.get(explicit);
        }

        // Если запускается из archparse/
        if (Files.exists(Paths.get("build.gradle"))) {
            return Paths.get("out/pool_ir.json");
        }

        return Paths.get("archparse/out/pool_ir.json");
    }
}
