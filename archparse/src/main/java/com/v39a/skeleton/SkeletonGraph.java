package com.v39a.skeleton;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.zip.GZIPInputStream;

/**
 * Узлы скелета, которые нужны IR тел методов: методы (чтобы взять их ID дословно),
 * call_site по (file, line, col) и анонимные типы по (file, line).
 */
public class SkeletonGraph {

    /** Узел метода скелета. owner — FQN типа-владельца без префикса "type:<module>:". */
    public record MethodNode(String id, String name, String owner, String module, int paramCount,
                             String file, int line, int end, boolean isAbstract) {}

    private final Map<String, String> callSiteByPos = new HashMap<>();
    private final Map<String, List<MethodNode>> methodsByFile = new HashMap<>();
    private final Map<String, List<MethodNode>> methodsByOwner = new HashMap<>();
    private final Map<String, String> anonymousTypeByPos = new HashMap<>();
    private final Map<String, Set<String>> callSitesByMethod = new HashMap<>();
    private final List<MethodNode> methods = new ArrayList<>();

    public static SkeletonGraph load(Path gz) throws IOException {
        try (InputStream in = new GZIPInputStream(Files.newInputStream(gz))) {
            return new SkeletonGraph(new ObjectMapper().readTree(in));
        }
    }

    private SkeletonGraph(JsonNode root) {
        for (Map.Entry<String, JsonNode> e : root.get("nodes").properties()) {
            JsonNode n = e.getValue();
            String kind = n.path("kind").asText();
            switch (kind) {
                case "call_site" -> {
                    callSiteByPos.put(pos(n.path("file").asText(), n.path("line").asInt(), n.path("col").asInt()), e.getKey());
                    callSitesByMethod.computeIfAbsent(n.path("method").asText(), k -> new TreeSet<>()).add(e.getKey());
                }
                case "method" -> {
                    String owner = n.path("owner").asText();
                    String ownerFqn = owner.substring(owner.indexOf(':', owner.indexOf(':') + 1) + 1);
                    MethodNode m = new MethodNode(e.getKey(), n.path("name").asText(), ownerFqn, n.path("module").asText(),
                            n.path("params_as_written").size(), n.path("file").asText(), n.path("line").asInt(),
                            n.path("end").asInt(), n.path("abstract").asBoolean());
                    methods.add(m);
                    methodsByFile.computeIfAbsent(m.file(), k -> new ArrayList<>()).add(m);
                    methodsByOwner.computeIfAbsent(ownerFqn, k -> new ArrayList<>()).add(m);
                }
                case "type" -> {
                    if ("anonymous".equals(n.path("type_kind").asText())) {
                        anonymousTypeByPos.put(n.path("file").asText() + "|" + n.path("line").asInt(), e.getKey());
                    }
                }
                default -> { }
            }
        }
    }

    static String pos(String file, int line, int col) {
        return file + "|" + line + "|" + col;
    }

    /** ID call_site скелета по позиции вызова или null. */
    public String callSite(String file, int line, int col) {
        return callSiteByPos.get(pos(file, line, col));
    }

    /** ID анонимного типа скелета, объявленного в строке, или null. */
    public String anonymousType(String file, int line) {
        return anonymousTypeByPos.get(file + "|" + line);
    }

    public List<MethodNode> methodsInFile(String file) {
        return methodsByFile.getOrDefault(file, List.of());
    }

    /** Метод типа по имени и числу аргументов, если он единственный. */
    public MethodNode uniqueMethod(String ownerFqn, String name, int argCount) {
        MethodNode found = null;
        for (MethodNode m : methodsByOwner.getOrDefault(ownerFqn, List.of())) {
            if (m.name().equals(name) && m.paramCount() == argCount) {
                if (found != null) {
                    return null;
                }
                found = m;
            }
        }
        return found;
    }

    public List<MethodNode> methods() {
        return methods;
    }

    public Set<String> callSitesOf(String methodId) {
        return callSitesByMethod.getOrDefault(methodId, Set.of());
    }
}
