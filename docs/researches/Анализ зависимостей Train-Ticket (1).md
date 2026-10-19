# **Архитектурно-статический анализ бенчмарка FudanSELab/train-ticket: восстановление графа межсервисных вызовов и персистентного слоя**

> **Устарело.** Обзор, написанный до выхода пакета участника, под задачу глобального графа сервисов. Действующий пайплайн — [ADR-005](../adr/adr-005_scenario_execution_pipeline.md).

Реконструкция архитектурной топологии распределенных микросервисных приложений статическими методами представляет собой нетривиальную исследовательскую задачу1. В отличие от динамического профилирования, основанного на сборе распределенных трасс (Dapper, Jaeger, Zipkin), статический анализ опирается исключительно на синтаксические деревья (AST), таблицы символов, семантические графы вызовов и конфигурационные дескрипторы развертывания1.  
Применительно к задаче восстановления графа ![][image1], где вершины ![][image2] представляют компоненты системы, а ориентированные ребра ![][image3] отражают синхронные RPC/HTTP-вызовы, асинхронные сообщения и транзакционный доступ к данным, целевой метрикой точности выступает коэффициент Жаккара (Intersection over Union, ![][image4])1:  
![][image5]  
Кодовая база микросервисного бенчмарка FudanSELab/train-ticket объединяет полиглотные компоненты, динамическую адресацию и гетерогенные схемы хранения данных, что создает специфические условия для алгоритмов статического извлечения зависимостей1.

## **1\. Паттерны межсервисного взаимодействия в FudanSELab/train-ticket**

### **1.1. Архитектурная эволюция: ветка master (v0.2.0) в сравнении с релизом v1.0.0**

Анализ истории версий и изменений репозитория показывает, что между версией v0.2.0 и мажорной реструктуризацией v1.0.0 (Pull Request \#227 «Reconstruction») произошла комплексная унификация протоколов взаимодействия и конфигурации2.

| Параметр сравнения | Ветка master (v0.2.0) | Релиз v1.0.0 (PR \#227 Reconstruction) |
| :---- | :---- | :---- |
| **Базовая платформа** | Spring Boot 1.5.x–2.0.x, Spring Cloud Dalton/Edgware2 | Spring Boot 2.4.x–2.6.x, Spring Cloud 2020.0.x (Ilford)7 |
| **Реестр сервисов** | Netflix Eureka (ts-eureka-auth-server, @EnableEurekaClient)2 | Нативное разрешение имен через DNS Kubernetes (CoreDNS) и Consul6 |
| **Шлюз маршрутизации** | Netflix Zuul 1.x (ts-gateway-service) | Spring Cloud Gateway (реактивный стек на базе Netty)6 |
| **Схема именования эндпоинтов** | Несогласованная: /inside\_pay/pay, /order/create, /station/query | Унифицированный RESTful-стиль: /api/v1/\<servicename\>/\<resource\> \[cite: 7\] |
| **Контракты данных (DTO)** | Дублирование POJO-классов внутри каждого микросервиса | Выделение централизованного модуля ts-common (edu.fudan.common.\*)7 |
| **Топология персистентности** | Жесткая привязка к единым СУБД ts-server-mysql и ts-server-mongo \[cite: 8\] | Поддержка режима изоляции баз данных \--independent-db \[cite: 7\] |

В версии v0.2.0 исходящие HTTP-вызовы разрешались через Eureka VIP (Virtual IP) либо жестко закодированные порты на localhost2. В v1.0.0 Eureka была полностью демонтирована7. Резолвинг хостов перешел на уровень K8s Service FQDN либо переопределяемые параметры окружения, что упростило статический семантический разбор URL7.

### **1.2. Механизмы исходящих HTTP-вызовов и сигнатуры методов**

В Java-сервисах train-ticket межсервисный транспорт базируется исключительно на org.springframework.web.client.RestTemplate2. Декларативные клиенты OpenFeign (@FeignClient) и реактивный клиент WebClient в кодовой базе сервисов не используются2.  
Вызовы разделяются на три ключевых паттерна:  
Метод RestTemplate.exchange используется во всех сценариях, где требуется явная передача HTTP-заголовков (в частности, заголовка авторизации Authorization: Bearer \<token\>) и строгая типизация ответа через generic-дескрипторы:

```java
// Файл: ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java
HttpEntity<Seat> requestEntity = new HttpEntity<>(seat, httpHeaders);
ResponseEntity<Response<Ticket>> re = restTemplate.exchange(
    getServiceUrl("ts-seat-service") + "/api/v1/seatservice/seats",
    HttpMethod.POST,
    requestEntity,
    new ParameterizedTypeReference<Response<Ticket>>() {}
);
Response<Ticket> result = re.getBody();
```

Точная сигнатура метода для статического сопоставления аргументов:

```java
public <T> ResponseEntity<T> exchange(
    String url, 
    HttpMethod method, 
    HttpEntity<?> requestEntity, 
    ParameterizedTypeReference<T> responseType, 
    Object... uriVariables
) throws RestClientException;
```

Методы postForObject и postForEntity применяются в служебных вызовах без кастомных заголовков либо при передаче простых структур данных:

```java
// Файл: ts-order-service/src/main/java/order/service/OrderServiceImpl.java
Response result = restTemplate.postForObject(
    getServiceUrl("ts-station-service") + "/api/v1/stationservice/stations/idlist",
    stationIdList,
    Response.class
);
```

Сигнатура метода:

```java
public <T> T postForObject(
    String url, 
    Object request, 
    Class<T> responseType, 
    Object... uriVariables
) throws RestClientException;
```

Методы getForObject и getForEntity используются для прямого чтения ресурсов по идентификатору:

```java
// Файл: ts-security-service/src/main/java/security/service/SecurityServiceImpl.java
ResponseEntity<Response<Order>> response = restTemplate.getForEntity(
    getServiceUrl("ts-order-service") + "/api/v1/orderservice/order/" + orderId,
    (Class<Response<Order>>) (Class<?>) Response.class
);
```

Сигнатура метода:

```java
public <T> ResponseEntity<T> getForEntity(
    String url, 
    Class<T> responseType, 
    Object... uriVariables
) throws RestClientException;
```

Для сокрытия сетевой топологии разработчики внедрили метод разрешения базового адреса getServiceUrl(String serviceName)9. В архитектуре v1.0.0 реализация хелпера централизована в модуле ts-common (либо дублируется в пакетах \*.service конкретных микросервисов)7:

```java
// Файл: ts-common/src/main/java/edu/fudan/common/util/ServiceResolver.java
public String getServiceUrl(String serviceName) {
    return "http://" + serviceName + ":" + getPortByServiceName(serviceName);
}
```

В среде Kubernetes порт может опускаться, если коммуникация маршрутизируется через стандартный порт сервиса: http\://ts-seat-service:18898 или http\://ts-seat-service/api/v1/...2. Для статического анализатора вызов getServiceUrl("ts-seat-service") служит прямым маркером целевой вершины графа ![][image6]9.

### **1.3. Формирование целевых URL-адресов**

Статический разбор выражений построения URL в синтаксическом дереве выявляет четыре устойчивых шаблона конструирования адресов:  
Конкатенация строковых литералов и строковых переменных представляет собой наиболее распространенный подход:

```java
getServiceUrl("ts-order-service") + "/api/v1/orderservice/order/" + orderId
```

На уровне AST Spoon это выражение транслируется в цепочку узлов CtBinaryOperator с бинарной операцией BinaryOperatorKind.PLUS. Левый лист содержит вызов метода getServiceUrl, средний — литерал пути, а правый — локальную переменную идентификатора9.  
Параметризация через встроенные механизмы шаблонов URI в RestTemplate встречается в вызовах чтения:

```java
restTemplate.getForObject("http://ts-user-service:12342/api/v1/userservice/users/{userId}", Response.class, userId);
```

Здесь целевой эндпоинт полностью содержится в строковом литерале CtLiteral, а переменная пути передается через массив uriVariables.  
Внедрение свойств из конфигурационного слоя application.yml через Spring-аннотацию @Value:

```java
@Value("${station.service.url:http://ts-station-service:12345}")
private String stationServiceUrl;
// ...
String target = stationServiceUrl + "/api/v1/stationservice/stations";
```

В данном случае анализатор должен связать поле класса с дескриптором конфигурации application.yml или взять значение fallback по умолчанию.  
Построение с использованием UriComponentsBuilder применяется в сервисе планирования маршрутов ts-route-plan-service:

```java
UriComponentsBuilder.fromHttpUrl(getServiceUrl("ts-route-service"))
    .path("/api/v1/routeservice/routes")
    .queryParam("from", fromStationId)
    .queryParam("to", toStationId)
    .build().encode().toUriString();
```

При разборе такого AST требуется трекинг цепочки вызовов построителя (fluent interface) для извлечения фрагментов путей из аргументов вызова .path(...).

### **1.4. Общий контейнер ответа Response и generic-десериализация**

В микросервисах train-ticket ответ стандартизирован с помощью класса-контейнера edu.fudan.common.util.Response\<T\>7:

```java
package edu.fudan.common.util;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import java.io.Serializable;

@Data
@AllArgsConstructor
@NoArgsConstructor
public class Response<T> implements Serializable {
    private int status;      // 1 - операция успешна, 0 - сбой
    private String msg;      // Описание статуса выполнения
    private T data;          // Сериализуемый DTO или коллекция DTO
}
```

Поскольку JVM выполняет стирание типов (type erasure), вызов restTemplate.postForObject(url, req, Response.class) стирает метаданные типа поля data. При десериализации парсер Jackson преобразует полезную нагрузку в сырой java.util.LinkedHashMap, что в runtime приводит к исключению ClassCastException при попытке приведения к конкретному DTO.  
Для сохранения целевой структуры типов микросервисы передают анонимный внутренний класс ParameterizedTypeReference\<Response\<T\>\>:

```java
// Файл: ts-travel-service/src/main/java/travel/service/TravelServiceImpl.java
ResponseEntity<Response<TripAllDetail>> re = restTemplate.exchange(
    getServiceUrl("ts-ticketinfo-service") + "/api/v1/ticketinfoservice/ticketinfo",
    HttpMethod.POST,
    requestEntity,
    new ParameterizedTypeReference<Response<TripAllDetail>>() {}
);
Response<TripAllDetail> response = re.getBody();
TripAllDetail detail = response.getData();
```

Для статического анализатора присутствие ParameterizedTypeReference\<Response\<TripAllDetail\>\> является источником семантических метаданных: тип узла в AST содержит явный аргумент generic-параметра, что позволяет восстановить тип возвращаемого контракта без динамического запуска.

## **2\. Работа с базами данных, брокерами сообщений и полиглот-сервисами**

### **2.1. Инвентаризация технологий персистентности и типов СУБД**

Персистентный слой train-ticket строго разделен между реляционной СУБД MySQL и документоориентированной СУБД MongoDB2. Фреймворк MyBatis в системе отсутствует: сервисы Java на реляционной СУБД построены на Spring Data JPA, а сервисы на документоориентированной СУБД — на Spring Data MongoDB2.

| Микросервис | Технологический стек доступа | СУБД | Ключевые Entity / Document |
| :---- | :---- | :---- | :---- |
| ts-order-service | Spring Data JPA (@Entity, @Table) | MySQL | Order (таблица orders) |
| ts-order-other-service | Spring Data JPA (@Entity, @Table) | MySQL | Order (таблица orders\_other) |
| ts-user-service | Spring Data JPA (@Entity, @Table) | MySQL | User (таблица user) |
| ts-auth-service | Spring Data JPA (@Entity, @Table) | MySQL | AuthUser (таблица auth\_user) |
| ts-admin-user-service | Spring Data JPA (@Entity, @Table) | MySQL | Прямой доступ к таблицам пользователей |
| ts-admin-order-service | Spring Data JPA (@Entity, @Table) | MySQL | Прямой доступ к таблицам заказов |
| ts-inside-payment-service | Spring Data JPA (@Entity, @Table) | MySQL | Payment (таблица inside\_payment) |
| ts-payment-service | Spring Data JPA (@Entity, @Table) | MySQL | PaymentRecord (таблица payment) |
| ts-security-service | Spring Data JPA (@Entity, @Table) | MySQL | SecurityConfig (таблица security\_config) |
| ts-verification-code-service | Spring Data JPA (@Entity, @Table) | MySQL | VerificationCode (таблица verification\_code) |
| ts-station-service | Spring Data MongoDB (@Document) | MongoDB | Station (коллекция station) |
| ts-train-service | Spring Data MongoDB (@Document) | MongoDB | TrainType (коллекция train\_type) |
| ts-route-service | Spring Data MongoDB (@Document) | MongoDB | Route (коллекция route) |
| ts-price-service | Spring Data MongoDB (@Document) | MongoDB | PriceConfig (коллекция price\_config) |
| ts-config-service | Spring Data MongoDB (@Document) | MongoDB | Config (коллекция config) |
| ts-contacts-service | Spring Data MongoDB (@Document) | MongoDB | Contacts (коллекция contacts) |
| ts-travel-service | Spring Data MongoDB (@Document) | MongoDB | Trip (коллекция trip) |
| ts-travel2-service | Spring Data MongoDB (@Document) | MongoDB | Trip (коллекция trip2) |
| ts-food-service | Spring Data MongoDB (@Document) | MongoDB | Food (коллекция food) |
| ts-station-food-service | Spring Data MongoDB (@Document) | MongoDB | StationFood (коллекция station\_food) |
| ts-train-food-service | Spring Data MongoDB (@Document) | MongoDB | TrainFood (коллекция train\_food) |
| ts-consign-price-service | Spring Data MongoDB (@Document) | MongoDB | ConsignPrice (коллекция consign\_price) |
| ts-consign-service | Spring Data MongoDB (@Document) | MongoDB | Consign (коллекция consign) |
| ts-assurance-service | Spring Data MongoDB (@Document) | MongoDB | Assurance (коллекция assurance) |
| ts-seat-service | Spring Data MongoDB (@Document) | MongoDB | Seat (коллекция seat) |
| ts-ticket-office-service | Native MongoDB Driver (mongodb)8 | MongoDB | Office (коллекция office) |
| ts-voucher-service | Django ORM (models.Model)8 | MySQL | Voucher (таблица voucher) |

### **2.2. Архитектурный антипаттерн «Shared Persistency»**

В исходной архитектуре train-ticket зафиксирован антипаттерн Shared Persistency (совместное использование хранилища несколькими независимыми сервисами), неоднократно описанный в работах по архитектурным запахам (architectural smells)11:  
Сервисы ts-order-service и ts-admin-order-service подключаются к одной схеме реляционной БД и разделяют таблицу orders4. Административный сервис не обращается к ts-order-service через REST API, а выполняет прямые SQL-запросы на чтение и модификацию сущностей Order, созданных бизнес-сервисом4.  
Сервисы ts-user-service, ts-auth-service и ts-admin-user-service совместно используют базу данных учетных записей8. Таблицы user и auth\_user находятся в единой схеме ts, доступной по реквизитам root:root к хосту ts-server-mysql:33068.  
В деплоймент-конфигурациях по умолчанию все MongoDB-сервисы обращаются к единому серверу ts-server-mongo:270172. Хотя каждый сервис в основном использует собственную коллекцию, в манифестах quickstart-k8s они делят общее дисковое хранилище (Shared Volume) и сетевой контур СУБД2. При генерации графа для метрики IoU статический анализатор должен формировать ребра ![][image7], где несколько вершин сервисов инцидентны единой вершине базы данных.

### **2.3. Асинхронное взаимодействие через брокеры сообщений**

В бенчмарке train-ticket в качестве брокера сообщений используется исключительно **RabbitMQ** (через библиотеку spring-boot-starter-amqp)12. Брокер Apache Kafka в официальном репозитории FudanSELab/train-ticket не задействован2.  
Топология очередей и точек обмена:

* Точка обмена (Exchange): Стандартный direct exchange (по умолчанию "" или email-exchange).  
* Очередь (Queue): Очередь email.  
* Продюсеры (Publishers): ts-order-service и ts-inside-payment-service13. При создании заказа или подтверждении успешной оплаты сервис формирует объект edu.fudan.common.util.Notification и отправляет его вызовом: rabbitTemplate.convertAndSend("email", notification)13.  
* Консьюмеры (Consumers): Сервис нотификаций ts-notification-service13.

```java
// Файл: ts-notification-service/src/main/java/notification/mq/RabbitReceive.java
package notification.mq;

import edu.fudan.common.util.Notification;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class RabbitReceive {

    @RabbitListener(queues = "email")
    public void process(Notification notification) {
        // Логика формирования почтового уведомления
    }
}
```

При восстановлении графа зависимостей статический анализатор должен детектировать вызов RabbitTemplate.convertAndSend(queueName, ...) как исходящее асинхронное ребро, а аннотацию @RabbitListener(queues \= "email") — как входящее ребро консьюмера, связывая сервисы через виртуальный узел Queue\[email\].

### **2.4. Полиглот-сервисы (Python, Node.js, Go)**

В репозитории присутствуют четыре микросервиса, реализованные не на платформе Java2:

| Сервис | Язык | Фреймворк | Входные маршруты (Inbound Routes) | Исходящие вызовы (Outbound Calls) |
| :---- | :---- | :---- | :---- | :---- |
| ts-ticket-office-service \[cite: 8\] | Node.js (JavaScript)2 | Express.js2 | GET /api/v1/officeservice/offices POST /api/v1/officeservice/offices GET /api/v1/officeservice/offices/{region} | **Отсутствуют**. Листовой узел архитектуры, взаимодействует напрямую с MongoDB через нативный драйвер mongodb8. |
| ts-voucher-service \[cite: 8\] | Python 32 | Django / Django REST2 | POST /api/v1/voucherservice/vouchers GET /api/v1/voucherservice/vouchers/{orderId} | Выполняет синхронный HTTP-вызов через библиотеку requests: GET http\://ts-order-service:12031/api/v1/orderservice/order/{orderId}. |
| ts-avatar-service \[cite: 8\] | Python 32 | Django / Flask14 | POST /api/v1/avatar GET /api/v1/avatar/{userId} | **Отсутствуют**. Выполняет файловые операции сохранения и чтения бинарных изображений на локальном томе. |
| ts-news-service \[cite: 8\] | Go (Golang)2 | Webgo2 | GET /api/v1/newsservice/news | **Отсутствуют**. Возвращает статические новостные сводки из локального in-memory хранилища. |

## **3\. Нагрузочные сценарии, цепочки вызовов и эталонные Ground-Truth графы**

### **3.1. Архитектурные цепочки ключевых runtime-сценариев**

На основе анализа репозитория нагрузочного генератора train-ticket-auto-query и публикаций лаборатории Fudan SE Lab (Xin Peng и др.) выделяются ключевые транзакционные цепочки выполнения7.

#### **Сценарий бронирования билета (Ticket Preservation)**

Пользователь инициирует бронирование билета на скоростной поезд через шлюз, направляющий запрос в ts-preserve-service по маршруту POST /api/v1/preserveservice/preserve4. Сервис выполняет проверку прав и ограничений аккаунта через ts-security-service (POST /api/v1/securityservice/securityCheck), после чего обращается к ts-travel-service (POST /api/v1/travelservice/trips/left) для валидации доступности рейса. Сервис путешествий каскадно связывается с ts-ticketinfo-service, который через фасад ts-basic-service агрегирует информацию из ts-station-service, ts-train-service, ts-route-service и ts-price-service. Далее ts-preserve-service вызывает ts-seat-service (POST /api/v1/seatservice/seats) для резервирования места в вагоне, извлекает контакты пассажира из ts-user-service (GET /api/v1/userservice/users/id/{userId}) и отправляет полезную нагрузку в ts-order-service (POST /api/v1/orderservice/order), где заказ сохраняется в статусе «Создан/Не оплачен». При наличии дополнительных опций параллельно вызываются ts-food-service и ts-consign-service.

#### **Сценарий оплаты заказа (Inside Payment)**

Клиент отправляет команду на проведение транзакции в ts-inside-payment-service по эндпоинту POST /api/v1/inside\_pay\_service/inside\_payment. Внутренний платежный шлюз связывается с внешним финансовым адаптером ts-payment-service (POST /api/v1/paymentservice/payment) для списания средств. При получении подтверждения формируется запрос в ts-order-service (POST /api/v1/orderservice/order/status), обновляющий состояние заказа на «Оплачен»4. Сервис заказов транзакционно сбрасывает событие в RabbitMQ (email), которое потребляется микросервисом ts-notification-service для генерации почтового квитка13.

#### **Сценарий возврата билета (Ticket Cancellation)**

Операция начинается с вызова ts-cancel-service по маршруту GET /api/v1/cancelservice/cancel/{orderId}/{loginId}. Сервис отмены выполняет запрос метаданных билета в ts-order-service (GET /api/v1/orderservice/order/{orderId}), рассчитывает размер удержания (штрафа) и обращается в ts-inside-payment-service (POST /api/v1/inside\_pay\_service/inside\_payment/refund) для возврата баланса. После успешного перевода средств ts-cancel-service обновляет статус заказа на «Отменен» через ts-order-service и направляет команду в ts-seat-service на разблокировку посадочного места.

#### **Сценарий планирования и поиска маршрута (Travel Route Planning)**

Клиент вызывает эндпоинт поиска в ts-route-plan-service (POST /api/v1/routeplanservice/routePlan/cheapestRoutes). Сервис планирования маршрута обращается к сервису топологии ts-route-service (GET /api/v1/routeservice/routes) для получения графа станций, а затем отправляет массив сегментов в ts-travel-service и ts-price-service для расчета стоимости поездки.

### **3.2. Неиспользуемые компоненты (Dead Code и нереференцированные эндпоинты)**

При статическом сопоставлении кодовой базы с динамическими трассами выявляются компоненты, которые регулярно классифицируются динамическими профилировщиками как неиспользуемые3:  
Административные микросервисы (ts-admin-basic-info-service, ts-admin-order-service, ts-admin-route-service, ts-admin-travel-service, ts-admin-user-service) изолированы от штатных пользовательских сценариев17. Они предназначены для служебного интерфейса администрирования. В стандартных нагрузочных профилях (train-ticket-auto-query) эти сервисы не вызываются, что делает их ребра «мертвыми» в динамическом ground-truth графе16.  
Дублирующие микросервисы-сателлиты:

* ts-travel2-service: Полный функциональный дубликат ts-travel-service, введенный разработчиками бенчмарка для эмуляции канареечных релизов (canary deployment) и A/B-тестирования. В стандартной маршрутизации API Gateway трафик на него не направляется.  
* ts-preserve-other-service и ts-order-other-service: Вызываются исключительно при бронировании билетов на поезда без литеры G и D (медленные поезда)4. Если тестовый генератор оперирует только скоростными маршрутами, оба сервиса полностью отсутствуют в распределенных трассах4.

Нереференцированные контроллеры и мок-эндпоинты: В ts-verification-code-service методы валидации капчи часто обходятся на уровне шлюза при автотестировании. В ts-avatar-service контроллеры загрузки аватаров пользователей остаются изолированными, поскольку фронтенд бенчмарка содержит заглушки для картинок профиля8.

### **3.3. Открытые репликационные пакеты и эталонные датасеты Ground-Truth**

Для оценки метрики IoU статического анализатора доступны следующие валидированные исследовательские датасеты:  
The Microservice Dependency Matrix Dataset (SANER 2024): Датасет размещен в открытом репозитории Zenodo (Record ID: 8106860, DOI: 10.5281/zenodo.8106860) авторами исследования метрик зависимостей1. Пакет содержит матрицы зависимостей эндпоинтов (Endpoint Dependency Matrix, EDM) и зависимостей данных (Data Dependency Matrix, DDM) для train-ticket v1.0.0 в форматах CSV и JSON1. В матрицах зафиксированы точные кортежи (caller\_service, caller\_endpoint, callee\_service, callee\_endpoint)4.  
Репликационный репозиторий Graal-Prophet: Проект доступен на GitHub (https\://github.com/cloudhubs/graal-prophet) и включает эталонный граф синтаксических связей, построенный на базе графовой модели Prophet AST для бенчмарка train-ticket1.  
Cloudhubs Microservice Test Coverage Benchmark: Датасет и тестовый стенд (https\://github.com/cloudhubs/microservice-tests), содержащий эталонное сопоставление статических эндпоинтов train-ticket с реальными динамическими распределенными трассами3.  
Материалы публикаций Fudan SE Lab по локализации сбоев: Репликационные пакеты статей MicroHECL (ICSE) и DeepTraLog (IEEE TSE), включающие эталонные топологические графы микросервисов train-ticket (41 узел, свыше 160 межсервисных связей) в форматах списков смежности JSON/NetworkX2.

## **4\. Специфика синтаксического анализа через Spoon и JavaParser**

### **4.1. Подводные камни статического связывания вызовов с контроллерами**

При сопоставлении клиентских вызовов RestTemplate с методами, аннотированными @RestController, возникают системные расхождения в представлении URI-путей9.

#### **Расхождения в именовании path-переменных**

В методе целевого контроллера переменная пути объявляется декларативно с локальным именем:

```java
// Сервис: ts-order-service, OrderController.java
@GetMapping(path = "/api/v1/orderservice/order/{orderId}")
public HttpEntity getOrderByOrderId(@PathVariable("orderId") String id) { ... }
```

Клиентский код в вызывающем сервисе использует конкатенацию локального поля:

```java
// Сервис: ts-security-service, SecurityServiceImpl.java
String url = getServiceUrl("ts-order-service") + "/api/v1/orderservice/order/" + accountId;
restTemplate.getForObject(url, Response.class);
```

При прямом строковом сопоставлении AST Spoon выявит несовпадение между литералом "{orderId}" и выражением конкатенации с переменной accountId.*Решение*: Преобразование всех путей @RequestMapping в параметризованные регулярные выражения. Шаблоны вида {\[^/\]+} в аннотациях контроллеров компилируются в regex-группы (\[^/\]+). Конкатенируемые динамические аргументы на клиенте (узлы AST типа CtVariableRead, CtInvocation) при синтаксическом анализе заменяются на wildcard \[^/\]+. Сопоставление путей выполняется через проверку пересечения регулярных выражений.

#### **Иерархическое комбинирование префиксов**

Контроллеры Spring Boot часто определяют базовый путь на уровне класса:

```java
@RestController
@RequestMapping("/api/v1/routeservice")
public class RouteController {
    @PostMapping(path = "/routes")
    public HttpEntity createRoute(...) { ... }
}
```

Анализатор должен агрегировать префиксы: path \= normalize(Class.path) \+ normalize(Method.path). Ошибки возникают при некорректной нормализации концевых и ведущих слешей (/api/v1/routeservice//routes), что требует применения пайплайна канонизации URI на графе.

#### **Полиморфизм сервисного уровня (Service \-\> ServiceImpl)**

Контроллеры train-ticket делегируют выполнение интерфейсам:

```java
@RestController
public class PreserveController {
    @Autowired
    private PreserveService preserveService; // Интерфейс
    
    @PostMapping("/api/v1/preserveservice/preserve")
    public HttpEntity preserve(@RequestBody OrderTicketsInfo info) {
        return ok(preserveService.preserve(info));
    }
}
```

Фактический вызов RestTemplate расположен внутри класса реализации PreserveServiceImpl. Статический парсер (Spoon) должен построить внутрисервисный граф вызовов (Intra-service Call Graph). При обнаружении вызова метода preserveService.preserve(...) механизм разрешения типов должен найти реализацию preserve.service.PreserveServiceImpl, войти в тело метода preserve и проследить поток управления (Control Flow) до точки вызова restTemplate.exchange(...).

#### **Разрешение вызовов getServiceUrl**

Поскольку имя целевого сервиса не фигурирует в аннотациях, статический анализатор должен содержать специализированное семантическое правило:

```java
// Spoon AST Inspection Rule
if (invocation.getExecutable().getSimpleName().equals("getServiceUrl")) {
    CtExpression<?> arg = invocation.getArguments().get(0);
    if (arg instanceof CtLiteral) {
        String targetServiceName = ((CtLiteral<?>) arg).getValue().toString();
        // Установка целевого микросервиса в контексте текущего исходящего ребра
    }
}
```

### **4.2. Алгоритм статического сопоставления межмодульных DTO-классов**

Микросервисы в train-ticket компилируются как независимые модули7. Класс заказа в сервисе создания заказа (order.entity.Order) и класс заказа в сервисе биллинга (inside\_payment.entity.Order) находятся в разных пакетах и имеют разные FQCN, несмотря на семантическую эквивалентность полей.  
Для разрешения связей между возвращаемым объектом контроллера и принимающим DTO клиента на статическом уровне используется алгоритм структурного анализа схемы:  
Сначала анализатор извлекает множество полей класса источника ![][image8] и класса назначения ![][image9]. При наличии аннотаций Jackson @JsonProperty("name") имя свойства берется из значения аннотации, иначе берется идентификатор поля CtField. Типы полей приводятся к каноническому базису типов ![][image10].  
Каждое поле ![][image11] представляется парой ![][image12]. Вычисляется коэффициент структурной эквивалентности:  
![][image13]  
Если рассчитанный коэффициент ![][image14] (где эмпирический порог ![][image15]), анализатор считает контракт согласованным и фиксирует направленное ребро передачи данных (Data Flow Dependency Edge) между эндпоинтом поставщика и клиентом потребителя4.

## **5\. Конфигурационный слой и правила сетевой маршрутизации**

### **5.1. Карта сетевой инфраструктуры, хостов и портов**

Каждый сервис в манифестах quickstart-docker-compose.yml и Kubernetes фиксирует выделенный порт, однозначно определяющий его в сетевом пространстве бенчмарка2:

| Микросервис | Внутренний порт | Назначение в архитектуре |
| :---- | :---- | :---- |
| ts-ui-dashboard | 8080 (NodePort 32677\)2 | Nginx Web Server \+ SPA-клиент (HTML/JS)2 |
| ts-gateway-service | 18888 | Центральный API Gateway6 |
| ts-auth-service | 12340 | Сервис аутентификации (JWT Token Provider) |
| ts-user-service | 12342 | Сервис профилей пользователей |
| ts-contacts-service | 12347 | Управление записной книжкой пассажиров |
| ts-station-service | 12345 | Справочник станций железной дороги |
| ts-train-service | 14567 | Справочник моделей и конфигураций поездов |
| ts-travel-service | 12346 | Маршруты, расписания и сегменты поездок |
| ts-order-service | 12031 | Процессинг основных заказов |
| ts-order-other-service | 12032 | Процессинг заказов на медленные поезда |
| ts-seat-service | 18898 | Алгоритмы распределения мест в вагонах |
| ts-inside-payment-service | 18673 | Внутренний баланс и расчет стоимости |
| ts-payment-service | 19001 | Внешний платежный шлюз |
| ts-security-service | 11188 | Контроль лимитов заказов и блокировок |
| ts-ticket-office-service | 16108 \[cite: 20\] | Сервис билетных касс (Node.js)8 |
| ts-news-service | 12862 \[cite: 20\] | Сервис новостной ленты (Golang)8 |
| ts-avatar-service | 17001 \[cite: 20\] | Хранилище аватаров (Python)8 |
| ts-voucher-service | 16101 | Сервис ваучеров и чеков (Python)8 |
| ts-server-mysql | 3306 | Централизованная база данных MySQL8 |
| ts-server-mongo | 27017 | Централизованная база данных MongoDB |
| rabbitmq | 5672, 15672 | Брокер сообщений AMQP и Management Dashboard |

### **5.2. Шлюз маршрутизации: конфигурации Nginx и Gateway**

Маршрутизация внешнего трафика в train-ticket организована по двухуровневой схеме2:

#### **Фронтенд-прокси Nginx (ts-ui-dashboard)**

Пользовательский браузер взаимодействует с контейнером ts-ui-dashboard через порт 8080 (в K8s проброшен через NodePort: 32677\)2. Конфигурационный файл nginx.conf содержит правила разграничения статики и API2:

```
server {
    listen 8080;
    server_name localhost;

    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    # Проксирование всех межсервисных вызовов на API Gateway
    location /api/v1/ {
        proxy_pass http://ts-gateway-service:18888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_connect_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

#### **Межсервисный шлюз (ts-gateway-service)**

Центральный шлюз ts-gateway-service принимает запросы по префиксу /api/v1/ и направляет их целевым микросервисам6. В v1.0.0 на базе Spring Cloud Gateway файл application.yml определяет предикаты маршрутизации6:

```json
server:
  port: 18888

spring:
  cloud:
    gateway:
      routes:
        - id: ts-order-service
          uri: http://ts-order-service:12031
          predicates:
            - Path=/api/v1/orderservice/**
        - id: ts-travel-service
          uri: http://ts-travel-service:12346
          predicates:
            - Path=/api/v1/travelservice/**
        - id: ts-seat-service
          uri: http://ts-seat-service:18898
          predicates:
            - Path=/api/v1/seatservice/**
        - id: ts-ticket-office-service
          uri: http://ts-ticket-office-service:16108
          predicates:
            - Path=/api/v1/officeservice/**
        - id: ts-voucher-service
          uri: http://ts-voucher-service:16101
          predicates:
            - Path=/api/v1/voucherservice/**
```

Для статического анализатора разбор файла application.yml сервиса шлюза является прямым методом идентификации входных шлюзовых ребер графа вида ![][image16].

### **5.3. Деплоймент-слой: Docker Compose и Kubernetes**

В файле deployment/docker-compose-manifests/quickstart-docker-compose.yml каждый сервис объявляется в рамках единой пользовательской bridge-сети2. Имена сервисов (например, ts-seat-service) служат DNS-хостами, что позволяет Java-коду выполнять обращение по адресу http\://ts-seat-service:18898 без модификации /etc/hosts2.  
В Kubernetes-манифестах (quickstart-ts-deployment-part1.yml, part2.yml, part3.yml) каждому микросервису соответствуют два ресурса2:

* Deployment: Управляет подами контейнеров, монтирует переменные окружения и ConfigMap.  
* Service: Создает внутренний виртуальный балансировщик типа ClusterIP со статическим портом, имя которого совпадает с именем сервиса (metadata.name: ts-order-service). Разрешение доменных имен внутри кластера делегируется CoreDNS (ts-order-service.default.svc.cluster.local).

Единственной точкой входа из внешней сети является сервис ts-ui-dashboard, объявленный как Type: NodePort с фиксированным внешним портом nodePort: 32677, перенаправляющим входящий трафик на внутренний порт 80802.

## **6\. Синтез архитектурных выводов для построения ML-модели и статического анализатора**

Для достижения высокой оценки метрики ![][image4] при восстановлении графа зависимостей train-ticket статический анализатор должен объединять многоуровневый синтаксический анализ и обработку инфраструктурных артефактов:

> 1. **Разрешение префиксов и маршрутов**: Анализатор на базе Spoon должен реализовывать двухуровневое связывание путей: нормализацию аннотаций @RequestMapping (класс \+ метод) и регулярное выражение для сопоставления с аргументами RestTemplate9.  
> 2. **Семантика хелперов**: Вызовы getServiceUrl(serviceName) требуют специального правила инспекции AST для извлечения целевого хоста из строковых литералов9.  
> 3. **Учет разделяемой персистентности (Shared Persistency)**: Реконструкция графа должна включать парсинг аннотаций Spring Data JPA (@Table) и Spring Data MongoDB (@Document), формируя явные связи сервисов с общими схемами MySQL и MongoDB, что отражает реальные архитектурные запахи системы8.  
> 4. **Асинхронные каналы передачи данных**: Обязателен анализ конфигурации RabbitMQ для связывания вызовов RabbitTemplate.convertAndSend со слушателями @RabbitListener через виртуальные узлы очередей12.  
> 5. **Полиглотный парсинг**: Для включения не-Java сервисов (ts-ticket-office-service, ts-voucher-service, ts-avatar-service, ts-news-service) статический конвейер должен дополняться разбором Express-роутов, Django URLs и Go Webgo2.  
> 6. **Калибровка по эталонным датасетам**: Валидацию полноты восстановленного графа следует выполнять относительно матриц EDM/DDM репликационного пакета SANER 2024 (Zenodo Record 8106860), отсекая неиспользуемые в штатных runtime-сценариях административные модули ts-admin-\*-service1.

#### **Источники**

> 1. The Microservice Dependency Matrix \- arXiv, [https\://arxiv.org/html/2309.02804v1](https://arxiv.org/html/2309.02804v1)  
> 2. GitHub \- softwarelanguageslab/onweer-trainticket, [https\://github.com/softwarelanguageslab/onweer-trainticket](https://github.com/softwarelanguageslab/onweer-trainticket)  
> 3. An Automated Approach to E2E and API Test Coverage Metrics, [https\://portal.findresearcher.sdu.dk/files/314158098/electronics-13-01913.pdf](https://portal.findresearcher.sdu.dk/files/314158098/electronics-13-01913.pdf)  
> 4. (PDF) The Microservice Dependency Matrix \- ResearchGate, [https\://www\.researchgate.net/publication/374643294\_The\_Microservice\_Dependency\_Matrix](https://www.researchgate.net/publication/374643294_The_Microservice_Dependency_Matrix)  
> 5. Graph-Based Root Cause Localization in Microservice ... \- Authorea, [https\://www\.authorea.com/doi/pdf/10.22541/au.167120541.12575611/v1?onload=true\&redirectToLatest=false\&embedded=true](https://www.authorea.com/doi/pdf/10.22541/au.167120541.12575611/v1?onload=true&redirectToLatest=false&embedded=true)  
> 6. Train Ticket \- A Benchmark Microservice System \- GitHub, [https\://github.com/xlab-uiuc/train-ticket](https://github.com/xlab-uiuc/train-ticket)  
> 7. FudanSELab/train-ticket \- A Benchmark Microservice System \- GitHub, [https\://github.com/FudanSELab/train-ticket](https://github.com/FudanSELab/train-ticket)  
> 8. Train Ticket \- A Benchmark Microservice System · GitHub, [https\://github.com/StreamAzure/Train-Ticket-Benchmark](https://github.com/StreamAzure/Train-Ticket-Benchmark)  
> 9. Train Ticket: /order/refresh may skip the ts-order-service to ts-station, [https\://github.com/FudanSELab/train-ticket/issues/310](https://github.com/FudanSELab/train-ticket/issues/310)  
> 10. train-ticket-aitest/CLAUDE.md at master · cloudhubs/train ... \- GitHub, [https\://github.com/cloudhubs/train-ticket-aitest/blob/master/CLAUDE.md](https://github.com/cloudhubs/train-ticket-aitest/blob/master/CLAUDE.md)  
> 11. Automated Code-Smell Detection in Microservices Through Static, [https\://www\.mdpi.com/2076-3417/10/21/7800](https://www.mdpi.com/2076-3417/10/21/7800)  
> 12. ORECA: Evaluating Cadence and Elasticity Impacts on Root Cause, [https\://aaltodoc.aalto.fi/bitstreams/d8b36f25-5574-4203-8e57-f0051cd3767c/download](https://aaltodoc.aalto.fi/bitstreams/d8b36f25-5574-4203-8e57-f0051cd3767c/download)  
> 13. DeepTraLog: Trace-Log Combined Microservice Anomaly Detection, [https\://cspengxin.github.io/publications/icse22-DeepTraLog.pdf](https://cspengxin.github.io/publications/icse22-DeepTraLog.pdf)  
> 14. Defining and evaluating MiSAR \- Brunel University Research Archive, [https\://bura.brunel.ac.uk/bitstream/2438/31652/3/FullText.pdf](https://bura.brunel.ac.uk/bitstream/2438/31652/3/FullText.pdf)  
> 15. S-razmi/train-ticket: Train Ticket \- A Benchmark ... \- GitHub, [https\://github.com/S-razmi/train-ticket](https://github.com/S-razmi/train-ticket)  
> 16. Train Ticket \- A Benchmark Microservice System \- Gitee, [https\://gitee.com/lyrain02/train-ticket?skip\_mobile=true](https://gitee.com/lyrain02/train-ticket?skip_mobile=true)  
> 17. Microservice Pattern Identification from Recovered Architectures of, [https\://escholarship.org/content/qt0ch0m8wd/qt0ch0m8wd\_noSplash\_849949707cdf6bb35260f26108746173.pdf](https://escholarship.org/content/qt0ch0m8wd/qt0ch0m8wd_noSplash_849949707cdf6bb35260f26108746173.pdf)  
> 18. Analyzing Evolution of Microservice-based Systems \- NSF PAR, [https\://par.nsf.gov/servlets/purl/10670942](https://par.nsf.gov/servlets/purl/10670942)  
> 19. advancing-static-code-analysis-with-language-agnostic ... \- SciSpace, [https\://scispace.com/pdf/advancing-static-code-analysis-with-language-agnostic-etlsny1x.pdf](https://scispace.com/pdf/advancing-static-code-analysis-with-language-agnostic-etlsny1x.pdf)  
> 20. Concern-Oriented MicroService Architecture \- Université de Lille, [https\://pepite-depot.univ-lille.fr/LIBRE/EDMADIS/2025/2025ULILB030.pdf](https://pepite-depot.univ-lille.fr/LIBRE/EDMADIS/2025/2025ULILB030.pdf)

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGYAAAAVCAYAAAC0aZsNAAADQUlEQVR4Xu2YW6hOQRTHFxLl7oTEg2vkwQnFg8STPBCvIuHEgxfypoPIJUVKyZui5MGlpDzgQR6EkFu5q4Mol0hEua9/a6ZvZrVnZp/9bd8+nb5f/WvvtdbMnpk9M3vtIWrSpEmTJhXyiTVDG7sgW1ijtLEo/VlvWX9ZD1jtrGOsm6zRrA+10IYzhPVU2dBOrYVeBNFGx2dVBF1HSPNtAeYF64JzXwhU2MH6zFrvu+ga6z4V71QZXGR9UbZhrLFUG5TprB5ehNw/I/HvZE3x3blB3etI6pnDmsaaSrJ6F7DeGZ9b/yJjK4ytAKsjxEnWe21sIL9IXkIW9sWE+MgaoY0FOELx55zSBmYNa6825uU76wqrj3Y4bCV5OVUwmXVOGx1iL2Y8yeCUAbam0HPALm1g+rK+sQZqR4rTFH+YZRVrkjY2iDes2drogO0XfchaUT+0oSBtJM84rOy3neuDzrULyoV8mWCP/EP5Go/trirQsdhqvkcSM1fZh7J2KFtRsM3jGcsc2zxjS4GYR9oY4ydJobXaURAkCZjdeYXtMw+pzh8iidns2PCSMOnKAvVn6awbFMDG5sYW6KkdzHDWYJK9cQBrEMl+WQWpTi0liTnv2JCotDj39ZI1uLhvNde9SLLELDAJddkoWQ+z2NXk6owX0ThCbbTg+4OYh+YeycKKmrtukHKjfr0C8c9n0/MNrBuOzwXbWKoPHrEXY3lCEoPOpsAqQxaUVyOlWJJUGzFb7URCBoYss0ww6Kj7gHY44ESinzYavlK6Dx62wDjtMOBIAf7X2hHgOfkrLKW89ebpVAdJHAZok++qG3xHUPcS7TAgydivjQ62v7nBTLtO4UKvSHwrlb3RoA1oa4yjJHEztSMCUl+U2acdDrNIYu5qh8FuozHgx87TKSaSFNxD/r9CG+sS6yXJOVmV4OOJI5EY2yk9QJrLJGXuaIcB/27IHBFzi2SbxLdrNcnxDI6Jfht/DPhjpypRcFaGA7/drOWs3r67UtCeE9qomEDxn9AQYyg9sPWAlY6J1ZXGs1QweNu0sQSO0/+p13KVJCnqtjwmOcEtG5xYZx3llEGe70+3AMdCi7WxDkLZaFkgS+3UT+4/U87pmS4wvUkAAAAASUVORK5CYII=>

[image2]: <data:image/png;base64,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>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAWCAYAAADJqhx8AAAA50lEQVR4Xu2RrQpCQRCFRzEJgsEnMNhERBBsdrFpFhEEo+9gtVkUbL6EyWrSB7D4AkaDgj/nsLs4d64/9wH84IO9c2aHy6zIH0saVhNa8HciZGEDbuADTmEFlmEdNuHWZyN35T17cU0lG4j7S2YtGwTa4hpWNlAwz9ligL/NhoGpz2HKn086sNzEDdBk4MzUPsLLlIujHbiGXd30jTCgJu5FJv47EXlxzUdTP5jvsIsYYYF9U1+o81KdY+zEDSjaQHGxBc2v9+/BsS1qOGBoix4OZs49ReBC+PZ3eb2AlnXmV3j2d/4onl5INMEf7+9FAAAAAElFTkSuQmCC>

[image4]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACEAAAAVCAYAAADID4fUAAABgUlEQVR4Xu2UvytFYRjHH1Iy+DVQBnWlsBEGhbghi81iYyOSovwD8gfIKBMLcpkNVxZ/gAwWiZEMsljE83if9/ac73nPPchgOJ/6Dvfzfc/pOe+55yXKyIgzy/kIpMUuSgGvlZyl9BGqOe2cNXLlMCfHqTRr0mjm7JG7/orTxak3fRtnWvsHTofpIvRTYMIfsELu+gIWBuknUFp66W+GOMbCIP04SksPlR+iityrqsNC8UMcYmGQPo/SUm6IJs4z55bzzhmK1l/4IQ6wMEg/itKSNMQTxf11wC2rS9uJEZSW0BC16rbBD6qfM25RXdp/IrSLJUJDDKjbAN+tfsu4BXWnxiHSyz0TCX0dk+pwJ/zaE+P82nPjEOnlzEikj+JDtKrbBz+lft04OdzuOI+cCuMtNygQv/XIG8X9fcAJ8hWJvwAvA8qJ2gC+hBzZS5wjcjfYJPd+a7Qf47xyZsg9Yaeu29UeuSTX54wrcl7M71/TSO6gkaG/wzxnh7OKRca/5hMFKmfa7aKChAAAAABJRU5ErkJggg==>

[image5]: <data:image/png;base64,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>

[image6]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADMAAAAVCAYAAADrVNYBAAACKElEQVR4Xu2XTUgVYRSGTxkSYeqqjNzULtAEQRIKu4TkLmhhP2QQtAolCGshSWC1iApa1MaIAkGKXEREtemHWpgUbSTBleDGQNqIuDEq3/d+53POHG40mcUE94GHme89c8c58/spUqZMmZXwo4TrU1uIfDA1WpEu54dNsFHCQd6C29PlIhsl1L/DE+lSPuHBnvehsg4+8GGeYTODPlTOwTof5hk2M+FD8AS+82HeYTPzPgRf4U4f5p0pCQ01mewm3GDG/w1DEprp1jFfvw+T8jL/+tmp9kEWLkto5qqOe+GWpLxMiw/+Mrt9kIUOCc3wYX8KR9PlIgNSuplKuNaHGfjVx3cznPVhFnZIaGYGLsKGdLnYJOvv4XOTd8EROAYLJv8EP8N7sF+zNfCshG3P6PKC1vbBt3BcQhOELyT+zRfwqGaZidMVP52JXJL0leGZHTZj/jbSZsYHdcmDe6zrrN3Qdb5kpnU91tol7N/u87eIzfwM30yEtxivJKc7EdtMhOPXZp0vHVKQMP87pbLWI3/YzF1Y60PDRdgKO+Eu2CyhgRqtf9MlKdXMaQkfYd5eh0y+H7404whPUtzHdVtYDfZKOGOP4DZ4W9IHzA/sAXgNHnY1woksG+mDR2CVqfGkXNH1Z5KcVF5JbndHx6vKgiQTUj5bbOw+fAWPw4+wXsLzMQe/6LbkpCS3MrUzjoKEFwD3x6sf2QMn4VaT5YI3bsx/P465bEUsAQCYeMrCcDKWAAAAAElFTkSuQmCC>

[image7]: <data:image/png;base64,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>

[image8]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAVCAYAAAAnzezqAAABX0lEQVR4Xu2VvyuFYRTHj0E2ikjZDAYlJhYifwCllEV3Md3uchMG/gJsBim5K1KKolB3xGhQilUJC2UTvsc5b857uH7lmO6nPr3nnOd573PeX88lKlMmTSt8/qYhVMJOWCBZZBd2wDY9jmotrIGES5JFGv2AEtpAC8kCp37AENrAKskCQ6bWDx9MvmHiP+eKpIE6U1uB+yYPJXnLD+ExvNW8x06KooJksSdTa4AHJg+FPzVu4MTVp10exjZJAwN+4AOqfOETanyhFHfwkb4+YR7uwCPYDKvhGeyF6zCn8/iRXsBzWIRNWi8JX/2sLzr4yudMnvzoDBzXuEuPdr/YhMMmTzEGJ0hO2INZOJKakYbnLcJBU+MG+kzOhGxYfFsZ3pzWYF5zbqBd44SQBmrhpMb8ODIaL9D7vYKfe7fGU3DZjP0abmBJ3SK5I/XwXr15m/r673pNsosW6Gdfzv/wAmxMTNFFd1PTAAAAAElFTkSuQmCC>

[image9]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACIAAAAUCAYAAADoZO9yAAABZUlEQVR4Xu2Uuy5FQRSGfwQn7g9ApxCNUEhEIzQ6jUYlEoVIKCRu8QJ0KonLG6CgUIjqRCERUamoJCp0GuL2r6zZydqTbbJPHBPF+ZIvZ+bfOzPrzKxsoEKF0uihXzmNwiF0szH/AalDpEKq6CN9p23es4QohcxDN9owmZzCgJnfmPGf8QwtpNlkclUHZh4FvxkLbj5nsigkhWzRHXpHn6C9k0XST2WlBlqEXbgDejU/MYF8zdvvByGWoYuum6yBdpm5TxPyFbLoByFe6Ct08xD19Jpe0FGkC5mENvYV3XXZB72lZ7TbZUFkwaIfZnBJB934COlCpGcE6ak9N56hm7SPNrosk2no0cmCJ3SWjqfeSGM3bvfmMj6lCyYbQYlXkwdp6E8z9wtpoZ3QP/NAa+kwXXHPp9xvWQidyJIZS95Kh+iay+wX+9fI5/4e2gOr0A3faC89ptt0H9oTCdI757TaZP+Pb7c8VCtNammqAAAAAElFTkSuQmCC>

[image10]: <data:image/png;base64,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>

[image11]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAwAAAAVCAYAAAByrA+0AAAAqklEQVR4XmNgGN6AG4hvAbEvEP8CYhlUaUwwFYj/A/EkKB2OKo0JQIpAmAuI2dDksAKQ4kfogrgAEwNEQz26BDrQBuIzQHyJAaLhCRCfRlGBA7QB8ScgZkSXwAVeMEBChyggwQBxTiK6BC5QxQDRwIIugQusZoBoIBr8YyBRAyyGiQYgxbPRBdHBOgaIQnEg/gjE7KjSmADmjCggzkGTwwrygfgeAySE8AIA70okSizm9x4AAAAASUVORK5CYII=>

[image12]: <data:image/png;base64,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>

[image13]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAABVCAYAAAD0f7hpAAAPaElEQVR4Xu3dC9Ct1RzH8eUW6eKWXNJ0qJSISk2SnNCFcm2EJkZUTIxbDWHQNFSKSW5JqFMpqSihiWmaKBoJg8SQOSVpopLI/fb8Zq3/7PX+z1rP5ezLu99zvp+ZNe/z/Nez372f/Z7z7v+7riEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwKJ4sg9govbwAQAAgKE+4QOYqPN8AAAAYKi2hO3KptzUlP+lcm1TrmrKd5vykyz+HXvAHKvdi8r3mnJ3VjdJ5/sAAADAUG0Jm2wdYhJzjq9Ibm7KB31wwh7ZlDNCTBIvacrBC6t767qXB4fJJ2wX+AAAAMBQXQmbkhslMZv7iuTIpuzrgxNyr6b8pynHNmWjLL53iC1iH8pifXTdi0w6YfuSDwAAAAzVlbCVugmflB0f15T1s/NJ0vPexwczStje6IMtSvcie2XHpfpxfNkHAAAAhlqdhO3f2fHDsuNJOiT0m2HpX1ub0r1s3JSTs/MHZceTcKEPAAAADNWWsG0VYoJzVhY7KcWm7ZM+UPEXH6io3Yu6XB+VxSbtIh8AAAAYqi1hOzfEJEcTC37blL+n88/kF03JCh+o+LMPVNTuZdrJ51d8AAAAYKi2hK2U0FzalE1dbBrO9oGKu3ygonYvPpY7vCmn+OBAF/sAAADAUEMTtr5dkOPqm7Dd4QMVtXs51cVy9w6rPqakbZmRr/oAAADAULWETTNBlax83lfMSN+E7TYfKBjnXvokbG1JHwkbAAAYWy1h03IUSlYe5ysKdmnKzk3ZMZ1rmY8d0rEWo83t35QnuFhJ34Ttdz5QMOReROu/bZmO84RN8QNCnElqe7BqlwQSNgBYAg71AaCilhwtptprKnUhltyTHdv1B6Xjl2SxB2bHxzflD+m4pm/CpkkEXfrei2jbLfs//dmw8HFKzuQxTTkmfdUODFq6Y6cQu1A9EjYAazX91f6pplzXlBOz+Duy41l4QajPZnt4Ux7dlE1C/MWur9piRyu2b5hdN03rNOXoELuNftGU3RZWL5p1Q1xKwd4bFb03es98i8w0vbopK5tyS1Ne7+qm4cVh/hZS9QmbErA/hTg27M4QB/Vr3bXav1klNEek421dPKdZmftl56XkJtc3YfuND2SG3kueVBo7t22rdk3ny9JXbctFCxsAFLwixF+c9ktXXRM6vz0s3KpG3R+KvzOLTZJ+gf/DBzP66/xrYfTXvT6otTWOtqrRB4dipfE32kjbHqPtd36fnWsJA21g/bcsVqLV4TWgWq0FD0ix+4W4nIHWnVpsSqy1x6Ldg5Y++EKIG2XbpuL/DTGxy+2Z6lT0Yaz3Rvejc33Vh/cfs2u0hVHJt5ry1zDq9hJ96Ooxev5p+n6YTXLYl0/YhtLPSEmR3ru8tcv/29S5EvN5dmAov25zWDpX2SfFlLC1LXNCwgZgraVflqW/kBXPE7a3pdi3s9gkKaHYzgcdtRjpNZzmK0JMqlT3LxdX7KGFmP8gkVLMuqGsJcArPediqd2XKLn0dUrGXuNivw7xOt9io5jGHOXWS/HzXNxcHmL9ChefJL0mf1+LadyE7bLsOP935e/x1hC7Sk2+vdW8sH8fOTvfIsQWOLH/u6J9TlekY2tpzJGwAVgrPTOs+gvVfDQM3wx6dWnQce115D4c4nW1lgV1kan+qelc61tpTIyna0rLF/jX8IwUO8jFc28N8Zon+ooZs/ewrXVC9fkHnpJkT9f490FqMXUNt7EWumlSa7D+bcyDcRM2vVe2nZO9b+p61/H26Vysu1ETEu7blBOyunlyfYgtuXJViK95eYgTJdR1LhrWcGY61h9XainXfT0ixXIkbADWSs8J8Rfoi3xFiOPFZpWw3RD6tdxpvEzXh7/qbVzTlXlF8soQr3mzr2j8yJ3rOj1nG7UK6roP+IoZ08BzvQ6NY6tRvb1/+tnnY6CM6pUAef591xgmHyvRVkK6TuP/pkUblvd5LbMwbsKmvUSVrGztKyo2D+0bus8DDXew7nL9f9kgjP49bBPKLfxKQktI2ACstexD/LgQx2WVaFyN9iJUd41WMzf6q14fyD9P53s15ZIQVzO3VgIlfvole3UYLVPg6flf6IMFecJRYgtzaiyWLM/qjHX5+e49yVvufhjidc/OYiVKdnVdKTmcJXWftb03kr9/+Xgz86oQ69/kKxq7Z8dK9HRdnyRbSbCuVYI4LXmX2mJrS5gxvj5LmADAGsm6GfOiwc75GKb7N+UtqS4fRK4PbnWrKa7B3+rakG+kmAbDvy7F1GKgWGmQfp8PW7U66Lq2GWQ23uzrviJj99il73XqctV1n/MVM9bn9XZdszLE+lIym7OWTrWUtHlsGD3ntLdf0nPUuspz+rc8pAAAMDc0YFkzNO3D1YrNiDSK+Vl/n07xp2QxfdApplmVuVrCUIp5mj2m69RiV2MzQg/2FRnVWwtcjSUabbNWjd1Tfv+zZsmsfhY1NiO0bdmG2s/H63vd6aH/tePSc/RpxTuqpby3Ke9pyrub8q6mHBnqXXMAACwqdX9aN5ZfJkMxn7Cpq7T0gayYukh9zF+r9cN8rKTv+LW2a5TIqV5jntp8LMTr+oyX6XrOWbDxa23J7K9CvKaty071XcmsBoX3vWe7TsuueFomRq2tK33FatLzvMEHAQBYk6llrfShrHOfsH08xT3Fdi/E/LUaNO1jJaXHel3XnBVivQY6t7F70tpvbTRrT9dpHbfFdE1ov2/pem/s51BbosNoUHzX9zJ2XW0G58tCv4TtIT5QoOeZ1hqBXTTD8VrKzAsArDVe25Rn+WBycVj1Q1nnPmE7KcU9xfxOAKUPepso0EXX/NIHM7aobmkpAFN6/hK1DOo6tR62sfF705wB2UfXfT0txPr3+YqMNvLWNV3JrHQ9n2jx3q7rNGNwpQ86Tw/tLYdGz6MZwAAArHEODXGcUYlmjfoPW537hM26Dz3F+iRsUorlbCamVk4v2SrEeo09alN7/hJdpxmlNXouXfNSF9f4PSUO+qqFfmWzMP7m3W30OtTlWaN6LZzbZuh703atkmbVa69Iv7uCaBkHzSLWuL+VWVzvjXbe0KQHFc1a1vfpm7Bp3bw2Go+mLt8hRV23AAAsKiVs+qDzkwtE2+OolS2na33CZpMOPMV2L8Rq17aNrdLim6XHiQaHq+65vsJRUqTrtJVVHzaOr0RJmur8Wm6apajxZKLuPg301/Nq30ddP3TzbtV3JVp6Hl2nJTk8S2S/6CsKaj+bErt/bdDt2R6RmjVcookcNptT97wyHWvG8fPS8ckhJmv6/vpe+6TjNn1fOwAAS44SNu2Rqa6900NMLrSm1RVh4QxJjdX6WRh9qGs2ptisTEss1OqkJT1sb0+tDaa1utTFqO5Mu/b2sHAZDD3/R7Jzo++lNd7scVobTWNXfhDiKumKaf2zWpekWrhU/+Mw+h4a6K7HXzG6rEoJhR5jrSzrN+XGEMeslbpedZ93h1GLma1Fp702fULRtXm37slec8lRYeF96f219+a6FNPrz1fH9/SzuSaM9g9V+WmIr7e0mGlOia+uV7e6qEXs3BRTYlry/rBw5rBmda5Mx9qSSIm5Nq3P6ft1tbBZl+880F68mJ49fAAA1gZ7Z8fLQxxsrw/U52fxWTixKf/0wTmhD2Alk1c35e1h1X1JPW3pZcnPZimmxMgnFDrvs27YN31gjmgdNrVwqjXthDDaEqxG3bb51llK2G7MzjUr1947/eEgOm5rfZULQlyweR6Mu9MB2p3nAwCA2fIJzVJ0SHasJOOGdFxK2G4N/Tbv9o9bytTCphY9o4TtpnSsSQ/m5WE0Q1f3vyy0L9Kra7oW+52VtoRNrb26X0tK1SKq/TX1R5KGGljcWrDnWe1eVDR2US3NVjdJ5/sAAGC2TgujPUCXqsPCaLsmJSPqLlwWRh9sQzfvVlffMT64xOme1wsxwVK3u7rD1YWscXaacSxHh9FsVU1+sUVsS5Tc3eiDi6gtYRPb8eMcX5HcHOIi0ZN2gA9U2M+gj657sfGMk6TWVADAItNEB9veaimycW3qGuy7rZHWP7PuP6/PTgtL0eNDHN+n7mVNjNAEA32VncOq4/n8zNrcpBOCcXUlbEpu9Jr1cy9RYrqvD06A/iDqozT5pabrXmTSP5++k4YAAFNW2msUKNHkD5/cLbauhK3UTZh3h6tFUa2uk7bCByqGJGylexFNvjGl+nEs9VZ4AAAwB1YnYdO2a0Y7SUzDWT5QMW7CtnGIy7IYmyk9KRf6AAAAwFBtCZuti5cnT7WdQibtbB+o6Juw1e5FLeTaH3haLvIBAACAodoSNlunThMLtG6hLaicL3UyLX0TNq2R2EftXtqSz8ObcooPDqQtzwAAAMbSlrCVEppLm7Kpi01DvmxKm74JW+1efCzXd9/gg30g43dfAQAAGGxowqadRmbhTB+ouNMHKmr3cqqLef4xJW3fQ4srAwAAjKWWsGkmqJKVPi1du4S4vMmO6VyzRndIx36Jk/3DaCu0NtqBo8+MWm0n12XIvYjW3NsyHecJm+JaH04TE2xLLy26S8IGAACmqpawaTkKJSu2L23NPdmxJTcHpWPt0WoxW3hZjg/dkwWUFHXtoKAFnLUWYpe+9yLaxUF7Fot2r8gTNiVnoi3atEC0vp4R4kzQnUI5wSRhAwAAY6slbKUuxBJdc0Q63tbFcxrkv192XkpuPO0VXNvaSS16eo4+W3z1vZc8qTR2brsg7JrOl6Wv2uWBFjYAADBVPmFTi5lare4IcXzYXSGuu7ZhflFm3RCvVzKjGZimlPioRWqoLUJM9rSLxuUhvh59r1oilxt6LweG8us22srNkr99UkwJW9usWRI2AAAwNp+wDXVZdpyPJ/OJz60hdpWafLeEeaE9Y/3rtnMljmqBE23NZvFjw2hXBmtpzJGwAQCAsY2bsClxsd0BLInZLR1vn87Fuhs1IUFjz07I6ubJ9U3ZMx1fFeJrXh7iRIlbUnyjMJrFqv1lbwvxvmxv3hwJGwAAGNu4CZu2plKysrWvqNDG62qhmmcar2azRLdrygZNWSedbxPKXapKQktI2AAAwNjGTdjQjoQNAACMbRMfwET1WXMOAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAq/o/fzkrKGevmu0AAAAASUVORK5CYII=>

[image14]: <data:image/png;base64,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>

[image15]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEsAAAAVCAYAAAAOyhNtAAACVUlEQVR4Xu2Xz4tOURzGv4QFxo9kJpk0fpVYKGYxoxkykaYsZCcytqaQIhuWpNQsZxZo0pQNkr9AahZEkRo2YkSUlbLBjOF53u+57vV07n3fV/LOW/dTn6b7nO9977nnnHvmXrOSkpKSkn/FLnge3oTnpK2Ij7ALbobr4FrYEWwJNavgSbgkHC+Ae2BvOG4q5sKf8C48CyfhoWxBATwvz+OhZns4noFvwl8erwntTQU7vjiSzZdM6YDP4BgchdfgVfgIHkzLrBO+hV/gfdifaWs6ODAKsz4NhX2WPlpZ3svxNvPVNUfypmOvxQdrEj7XUOC5yim4QbKt5oP1V7TBcfgYPsnI5dudqfsfcF+JDdYL+FnDKnBQvmpo6WD1wEHY/mdzPt/gBByAN+AUPAaPwsNpWRQu44fwQx1y8y7issUH66l5vlIbCmB97B62mN930pcR89qlvysi8NnNwg2Pm2IjuWDxweLGzXyFNuTAyb+nYQEPLL4Kc2FnuCwbSd5jyP3qh1VfmYQrnk/LRW0o4JbFrxuFnZiGC7WhCq1wfR1WY4fFO81HmKurFk6b/wZfEZSN5lvNsOTXLX7dKHx75WzUA2fwlflFanVe5cx82B7rNG/wkoY53Db/Db7BKyfM215KfifkNfHafEZmA3zcVkumN8KJYrZbcpJMzHJtMN/EP0nG/46sPyN5LizeqWGD4L7JmU5W4Sb4PW2usMi8zwOSk2Sw9Csg4Yj5t2HCO/P6WvbDCvs1aDDL4AHzj+l6J5HvT0MaCtxruW9dMf9MKikpmd38Almjjbuy1qD+AAAAAElFTkSuQmCC>

[image16]: <data:image/png;base64,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>