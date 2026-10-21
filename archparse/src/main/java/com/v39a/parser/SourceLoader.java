package com.v39a.parser;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.v39a.enumres.EnumResolver;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * Единый загрузчик исходных файлов проекта: однократный параллельный разбор AST
 * для EntityScanner и MethodIrWriter, плюс предварительная индексация enum в памяти.
 */
public class SourceLoader {

    public record SourceFile(String rel, String module, CompilationUnit cu) {
        public String relFile() {
            return rel;
        }
    }

    public static List<SourceFile> parseAll(Path targetsDir) throws IOException {
        List<Path> files;
        try (Stream<Path> walk = Files.walk(targetsDir)) {
            files = walk.filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> rel(targetsDir, p).contains("/src/main/java/"))
                    .sorted()
                    .collect(Collectors.toList());
        }

        ThreadLocal<JavaParser> parser = ThreadLocal.withInitial(JavaParser::new);
        List<SourceFile> parsed = files.parallelStream().map(p -> {
            String rel = rel(targetsDir, p);
            try {
                return parser.get().parse(p).getResult()
                        .map(cu -> new SourceFile(rel, rel.substring(0, rel.indexOf('/')), cu))
                        .orElse(null);
            } catch (Exception e) {
                System.err.println("Parse error, skipped: " + rel + ": " + e.getMessage());
                return null;
            }
        }).filter(Objects::nonNull).collect(Collectors.toList());

        // Индексация всех enum проекта в памяти без повторного чтения с диска
        for (SourceFile sf : parsed) {
            EnumResolver.indexCompilationUnit(sf.cu());
        }

        return parsed;
    }

    public static String rel(Path root, Path p) {
        return root.relativize(p).toString().replace('\\', '/');
    }
}
