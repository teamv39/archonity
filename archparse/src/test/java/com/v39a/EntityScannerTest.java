package com.v39a;

import com.v39a.model.EntityReportIR;
import com.v39a.model.MethodIR;
import com.v39a.parser.EntityScanner;
import com.v39a.skeleton.SkeletonGraph;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

public class EntityScannerTest {

    private static EntityReportIR report;

    @BeforeAll
    static void scan() throws Exception {
        Path targets = null;
        for (String cand : new String[]{"../hackaton/tt-challenge/targets/trainticket", "hackaton/tt-challenge/targets/trainticket"}) {
            if (Paths.get(cand).toFile().isDirectory()) {
                targets = Paths.get(cand);
                break;
            }
        }
        assertNotNull(targets, "targets/trainticket must exist");
        report = new EntityScanner(targets, SkeletonGraph.load(targets.resolve("../../skeleton/trainticket.json.gz"))).scan();
    }

    private static EntityReportIR.Entity entity(String type) {
        return report.entities.stream().filter(e -> e.type.equals(type)).findFirst()
                .orElseThrow(() -> new AssertionError("entity not found: " + type));
    }

    private static EntityReportIR.RepositoryCall call(String fileSuffix, int line, String callee) {
        Optional<EntityReportIR.RepositoryCall> c = report.repositoryCalls.stream()
                .filter(x -> x.file.endsWith(fileSuffix) && x.line == line && x.callee.equals(callee)).findFirst();
        return c.orElseThrow(() -> new AssertionError("call not found: " + fileSuffix + ":" + line + " " + callee));
    }

    @Test
    public void testEntitiesTablesAndConstructors() {
        // Order: тело конструктора с вызовами, таблица из @Table(name)
        EntityReportIR.Entity order = entity("order.entity.Order");
        assertEquals("orders", order.table);
        assertEquals("method:ts-order-service:order.entity.Order#<init>()", order.noArgCtor);
        assertTrue(order.ctorStatements > 0);

        // Contacts: пустой конструктор (только комментарий), в эталоне S0 его нет
        EntityReportIR.Entity contacts = entity("contacts.entity.Contacts");
        assertEquals(0, contacts.ctorStatements);

        // Комментарий и присваивание в одной строке: тело непустое
        assertEquals(1, entity("price.entity.PriceConfig").ctorStatements);
        assertEquals(1, entity("food.entity.StationFoodStore").ctorStatements);

        // Имя таблицы по правилу Spring и id в конструкторе
        EntityReportIR.Entity route = entity("route.entity.Route");
        assertEquals("route", route.table);
        assertTrue(route.ctorAssignsId);
        assertEquals("train_type", entity("train.entity.TrainType").table);
        assertEquals("trip2", entity("travel2.entity.Trip").table);

        // Встраиваемый TripId резолвится по импорту
        assertTrue(entity("travel.entity.Trip").embedded.contains("edu.fudan.common.entity.TripId"));

        // Lombok-конструктор не является узлом
        assertNull(entity("consign.entity.ConsignRecord").noArgCtor);
    }

    @Test
    public void testConstructorIrResolvesEnumCalls() {
        MethodIR ctor = report.constructors.stream()
                .filter(m -> m.getMethodId().equals("method:ts-common:edu.fudan.common.entity.Order#<init>()"))
                .findFirst().orElseThrow();
        assertEquals(2, ctor.getCalls().stream().filter(c -> "ENUM".equals(c.getKind())).count());
        assertTrue(ctor.getCalls().stream().anyMatch(c -> c.getCallee().equals("Date2String")));
    }

    @Test
    public void testRepositoryOperationsAndExpectations() {
        String assurance = "assurance/service/AssuranceServiceImpl.java";
        // Проверка «уже существует» перед созданием: успешный путь ждёт пустой результат
        EntityReportIR.RepositoryCall exists = call(assurance, 54, "findByOrderId");
        assertEquals("READ", exists.operation);
        assertEquals("EMPTY", exists.expects);
        assertEquals("assurance.entity.Assurance", exists.entity);

        // save сущности с id из аргумента конструктора: merge
        EntityReportIR.RepositoryCall save = call(assurance, 64, "save");
        assertEquals("SAVE", save.operation);
        assertEquals(Boolean.TRUE, save.idAssigned);

        // if (!route.isPresent()) { error } else { success }: успешный путь ждёт строку
        assertEquals("ROWS", call("route/service/RouteServiceImpl.java", 82, "findById").expects);

        // Отказ с логом и Response(1, "already exists"): тоже путь отказа
        assertEquals("EMPTY", call("travel/service/TravelServiceImpl.java", 61, "findByTripId").expects);

        // Список без проверки: решает состояние
        assertEquals("UNKNOWN", call("order/service/OrderServiceImpl.java", 128, "findByAccountId").expects);

        // id задаётся сеттером перед save
        EntityReportIR.RepositoryCall orderSave = call("order/service/OrderServiceImpl.java", 95, "save");
        assertEquals(Boolean.TRUE, orderSave.idAssigned);

        // new Payment() без id: persist
        EntityReportIR.RepositoryCall paySave = call("inside_payment/service/InsidePaymentServiceImpl.java", 120, "save");
        assertEquals(Boolean.FALSE, paySave.idAssigned);
    }

    private static EntityReportIR.CollectionField collection(String type, String field) {
        return entity(type).collections.stream().filter(c -> c.field.equals(field)).findFirst()
                .orElseThrow(() -> new AssertionError("collection not found: " + type + "." + field));
    }

    @Test
    public void testEntityCollections() {
        // Имя по умолчанию «таблица сущности_поле», ленивая
        assertEquals("route_stations", collection("route.entity.Route", "stations").table);
        assertEquals("LAZY", collection("route.entity.Route", "distances").fetch);
        // @CollectionTable(name) и fetch = EAGER
        EntityReportIR.CollectionField storeFood = collection("food.entity.StationFoodStore", "foodList");
        assertEquals("station_food_list", storeFood.table);
        assertEquals("EAGER", storeFood.fetch);
        // @CollectionTable без name
        assertEquals("user_roles", collection("auth.entity.User", "roles").table);
        assertEquals("food_delivery_order_food_list",
                collection("food_delivery.entity.FoodDeliveryOrder", "foodList").table);
    }

    @Test
    public void testLazyCollectionsLoadedByMethod() {
        String route = "route/service/RouteServiceImpl.java";
        // Сущность только возвращается: коллекции загрузит сериализация ответа
        assertEquals(java.util.List.of(), call(route, 82, "findById").collectionsLoaded);
        // route.getStations().contains(...) в цикле: stations грузятся, distances нет
        assertEquals(java.util.List.of("stations"), call(route, 105, "findAll").collectionsLoaded);
        // Геттер внутри return не грузит коллекцию
        assertEquals(java.util.List.of(),
                call("trainFood/service/TrainFoodServiceImpl.java", 54, "findByTripId").collectionsLoaded);
        // createToken(user) кладёт user.getRoles() в токен: заход на уровень в проектный метод
        assertEquals(java.util.List.of("roles"),
                call("auth/service/impl/TokenServiceImpl.java", 90, "findByUsername").collectionsLoaded);
        assertEquals(java.util.List.of(),
                call("auth/security/UserDetailsServiceImpl.java", 29, "findByUsername").collectionsLoaded);
        // Только EAGER-коллекции: поле не пишется
        assertNull(call("food/service/StationFoodServiceImpl.java", 102, "findByStationNameIn").collectionsLoaded);
    }

    @Test
    public void testElementCallbacks() {
        // accountOrders.contains(order) вызывает order.equals(элемент): рукописный equals сущности
        EntityReportIR.RepositoryCall create = call("order/service/OrderServiceImpl.java", 89, "findByAccountId");
        assertNotNull(create.elementCallbacks);
        assertEquals("method:ts-order-service:order.entity.Order#equals(java.lang.Object)", create.elementCallbacks.get(0).method);
        assertEquals("contains", create.elementCallbacks.get(0).via);
        assertEquals(90, create.elementCallbacks.get(0).line);
        assertNotNull(call("other/service/OrderOtherServiceImpl.java", 93, "findByAccountId").elementCallbacks);
        // Чтение без contains: поля нет
        assertNull(call("order/service/OrderServiceImpl.java", 128, "findByAccountId").elementCallbacks);
    }

    @Test
    public void testSpringPhysicalNaming() {
        assertEquals("station_food_store", springName("StationFoodStore"));
        assertEquals("price_config", springName("PriceConfig"));
        assertEquals("route", springName("Route"));
    }

    private static String springName(String s) {
        return EntityScanner.springPhysicalName(s);
    }
}
