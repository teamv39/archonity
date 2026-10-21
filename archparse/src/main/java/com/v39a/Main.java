package com.v39a;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.v39a.model.EntityReportIR;
import com.v39a.parser.EntityScanner;
import com.v39a.parser.MethodIrWriter;
import com.v39a.skeleton.SkeletonGraph;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;

public class Main {

    public static void main(String[] args) throws IOException {
        String repoRootStr = null;
        String skeletonStr = null;
        String outputPathStr = null;
        String mode = "bodies"; // bodies: IR тел всех методов скелета; entities: сущности и вызовы репозиториев

        for (int i = 0; i < args.length; i++) {
            if ("--targets-dir".equals(args[i]) || "--repo-root".equals(args[i])) {
                if (i + 1 < args.length) repoRootStr = args[++i];
            } else if ("--skeleton".equals(args[i])) {
                if (i + 1 < args.length) skeletonStr = args[++i];
            } else if ("--output".equals(args[i]) || "-o".equals(args[i])) {
                if (i + 1 < args.length) outputPathStr = args[++i];
            } else if ("--mode".equals(args[i])) {
                if (i + 1 < args.length) mode = args[++i];
            }
        }
        if (repoRootStr == null || skeletonStr == null) {
            System.err.println("Usage: --targets-dir <корень исходников> --skeleton <скелет .json.gz> "
                    + "[--mode bodies|entities] [-o <выход>]");
            System.exit(2);
        }

        Path targetsDir = Paths.get(repoRootStr);
        Path skeletonPath = Paths.get(skeletonStr);
        SkeletonGraph skeleton = SkeletonGraph.load(skeletonPath);

        if ("entities".equalsIgnoreCase(mode)) {
            Path outputFile = resolveOutputFile(outputPathStr, "entity_ir.json");
            System.out.println("archparse: Scanning entities and repository calls");
            System.out.println("Targets directory: " + targetsDir.toAbsolutePath());
            EntityReportIR report = new EntityScanner(targetsDir, skeleton).scan();
            if (outputFile.getParent() != null) {
                Files.createDirectories(outputFile.getParent());
            }
            new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT).writeValue(outputFile.toFile(), report);
            System.out.printf("Finished! %d entities, %d repository calls, %d constructors saved to %s%n",
                    report.entities.size(), report.repositoryCalls.size(), report.constructors.size(),
                    outputFile.toAbsolutePath());
            return;
        }

        if ("bodies".equalsIgnoreCase(mode)) {
            Path outDir = outputPathStr != null ? Paths.get(outputPathStr) : resolveOutputFile(null, "ir");
            System.out.println("archparse: IR of all method bodies (README 3.6)");
            System.out.println("Targets directory: " + targetsDir.toAbsolutePath());
            System.out.println("Skeleton: " + skeletonPath.toAbsolutePath());
            MethodIrWriter.Result r = MethodIrWriter.build(targetsDir, skeleton);
            Files.createDirectories(outDir);
            ObjectMapper mapper = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);
            for (Map.Entry<String, com.fasterxml.jackson.databind.node.ObjectNode> e : r.modules.entrySet()) {
                mapper.writeValue(outDir.resolve(e.getKey() + ".json").toFile(), e.getValue());
            }
            System.out.printf("Finished! %d methods in %d modules, %d skeleton call sites, %d ircalls -> %s%n",
                    r.methods, r.modules.size(), r.callSites, r.irCalls, outDir.toAbsolutePath());
            System.out.printf("Coverage: %d skeleton methods missing, %d declarations unmatched, %d call sites uncovered, "
                            + "%d duplicated, %d foreign%n", r.missingMethods.size(), r.unmatchedDeclarations.size(),
                    r.uncoveredCallSites.size(), r.duplicateCallSites.size(), r.foreignCallSites.size());
            r.missingMethods.stream().limit(20).forEach(m -> System.out.println("  missing: " + m));
            r.unmatchedDeclarations.stream().limit(20).forEach(m -> System.out.println("  unmatched: " + m));
            r.uncoveredCallSites.stream().limit(20).forEach(m -> System.out.println("  uncovered: " + m));
            r.duplicateCallSites.stream().limit(10).forEach(m -> System.out.println("  duplicate: " + m));
            r.foreignCallSites.stream().limit(10).forEach(m -> System.out.println("  foreign: " + m));
            return;
        }

        System.err.println("Unknown mode: " + mode + ". Available modes: 'bodies' (default), 'entities'.");
        System.exit(1);
    }

    private static Path resolveOutputFile(String explicit, String defaultName) {
        if (explicit != null) {
            return Paths.get(explicit);
        }

        // Артефакты archparse, которые читает движок: data/entity_ir.json и data/ir/<module>.json.
        // Если запускается из archparse/
        if (Files.exists(Paths.get("build.gradle"))) {
            return Paths.get("../data/" + defaultName);
        }

        return Paths.get("data/" + defaultName);
    }
}
