package com.v39a;

import com.fasterxml.jackson.databind.JsonNode;
import com.v39a.parser.MethodIrWriter;
import com.v39a.skeleton.SkeletonGraph;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Predicate;

import static org.junit.jupiter.api.Assertions.*;

public class MethodIrWriterTest {

    private static MethodIrWriter.Result result;

    @BeforeAll
    static void build() throws Exception {
        Path base = null;
        for (String cand : new String[]{"../hackaton/tt-challenge", "hackaton/tt-challenge"}) {
            if (Paths.get(cand, "targets/trainticket").toFile().isDirectory()) {
                base = Paths.get(cand);
                break;
            }
        }
        assertNotNull(base, "hackaton/tt-challenge must exist");
        result = MethodIrWriter.build(base.resolve("targets/trainticket"),
                SkeletonGraph.load(base.resolve("skeleton/trainticket.json.gz")));
    }

    private static JsonNode method(String module, String idPart) {
        JsonNode methods = result.modules.get(module).get("methods");
        for (var e : methods.properties()) {
            if (e.getKey().contains(idPart)) {
                return e.getValue();
            }
        }
        throw new AssertionError("method not found: " + idPart);
    }

    private static List<JsonNode> find(JsonNode root, Predicate<JsonNode> p) {
        List<JsonNode> out = new ArrayList<>();
        walk(root, p, out);
        return out;
    }

    private static void walk(JsonNode n, Predicate<JsonNode> p, List<JsonNode> out) {
        if (n == null) {
            return;
        }
        if (n.isObject() && p.test(n)) {
            out.add(n);
        }
        n.forEach(c -> walk(c, p, out));
    }

    @Test
    public void testSkeletonCoverage() {
        assertEquals(1196, result.methods);
        assertEquals(42, result.modules.size());
        assertEquals(List.of(), result.missingMethods);
        assertEquals(List.of(), result.unmatchedDeclarations);
        assertEquals(List.of(), result.uncoveredCallSites);
        assertEquals(List.of(), result.duplicateCallSites);
        assertEquals(List.of(), result.foreignCallSites);
        assertEquals(8961, result.callSites);
        for (JsonNode doc : result.modules.values()) {
            assertEquals(MethodIrWriter.SCHEMA, doc.get("schema").asText());
            assertTrue(find(doc, n -> n.has("text") && !n.has("op")).isEmpty(), "unparsed expression in " + doc.get("module"));
        }
    }

    @Test
    public void testStatementsAndCalls() {
        JsonNode m = method("ts-cancel-service", "CancelServiceImpl#cancelOrder(");
        assertEquals(45, m.get("line").asInt());
        JsonNode first = m.get("body").get(0);
        assertEquals("assign", first.get("op").asText());
        assertEquals("Response<Order>", first.get("decl").asText());
        assertTrue(first.at("/expr/call").asText().endsWith("@48:39"));
        assertEquals("param", first.at("/expr/args/0/ref").asText());
        JsonNode iff = m.get("body").get(1);
        assertEquals("b49", iff.get("id").asText());
        assertEquals("==", iff.at("/cond/bin").asText());
        assertEquals(1, iff.at("/cond/r/lit").asInt());
    }

    @Test
    public void testEnumConstantsWithArguments() {
        JsonNode m = method("ts-cancel-service", "CancelServiceImpl#cancelOrder(");
        List<JsonNode> paid = find(m, n -> "PAID".equals(n.path("constant").asText()));
        assertFalse(paid.isEmpty());
        assertEquals("edu.fudan.common.entity.OrderStatus", paid.get(0).get("enum").asText());
        assertEquals(1, paid.get(0).at("/args/0/lit").asInt());
    }

    @Test
    public void testLambdaMethodRefAndAnonymous() {
        JsonNode create = method("ts-food-delivery-service", "FoodDeliveryServiceImpl#createFoodDeliveryOrder(");
        List<JsonNode> refs = find(create, n -> n.has("method_ref"));
        assertTrue(refs.stream().allMatch(r -> r.has("call")), "method refs bound to call_site");

        JsonNode token = method("ts-auth-service", "TokenServiceImpl#getToken(");
        List<JsonNode> lambdas = find(token, n -> n.has("lambda"));
        assertFalse(lambdas.isEmpty());
        assertEquals("return", lambdas.get(0).at("/lambda/body/0/op").asText());

        List<JsonNode> anon = find(result.modules.get("ts-common"), n -> n.has("anon"));
        assertFalse(anon.isEmpty());
        assertTrue(anon.stream().allMatch(a -> a.get("anon").asText().startsWith("type:")));
    }
}
