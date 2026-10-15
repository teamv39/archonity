package com.v39a;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.github.javaparser.StaticJavaParser;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
public class Main {
    public static void main(String[] args) throws IOException {

        // Концепт

        String repoPath = args.length > 0 ? args[0] : "./data/train-ticket";
        String outputPath = args.length > 1 ? args[1] : "./output/confirmed_edges.json";
        Path repoRoot = Path.of(repoPath).toAbsolutePath();
        System.out.printf("RepoPath: %s, outputPath: %s", repoRoot, outputPath);

        ObjectMapper mapper = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);

        try (var stream = Files.walk(repoRoot)) {
            stream.filter(Files::isRegularFile)
                    .filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> !p.toString().contains("/test/"))
                    .forEach(path -> {
                        try {
                            var cu = StaticJavaParser.parse(path);
                            Parser.parse(cu);
                        } catch (Exception e) {
                            System.err.println("Ошибка парсинга: " + path);
                        }
                    });
        }

        mapper.writeValue(new File(outputPath), Parser.getAllEndpoints());
        System.out.println("Готово! Найдено эндпоинтов: " + Parser.getAllEndpoints().size());
    }
}