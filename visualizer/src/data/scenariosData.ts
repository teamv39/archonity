// Автоматически сгенерировано scripts/export_visualizer_data.py
import type { RuntimeScenario } from '../types/graph';

export const TOPOLOGY_HUB_EXCLUSIONS = new Set<string>([
  'ts-eureka-service',
  'ts-eureka-auth-server',
  'ts-config-service',
  'rabbitmq',
  'zipkin',
  'ts-gateway-service',
]);

export const BENCHMARK_SCENARIOS: RuntimeScenario[] = [
  {
    "id": "S0",
    "name": "S0: Калибровка пользователя и контактов",
    "title": "My account: contacts, orders of both train types, paid orders, luggage consignments",
    "description": "A registered passenger logs in and opens their contact book. They refresh their list of orders twice — for high-speed (GaoTie/DongChe) trains and for regular ('Other' type) trains, which are kept separately — and then refresh the orders once more with the filter 'Paid' status. Finally they look up the luggage consignments registered on their account. Nothing is searched, booked or paid.",
    "steps": [
      {
        "step": 1,
        "action": "Log in with username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to log in with username and password, which corresponds to the login action in the web UI. Handler H55 is the specific endpoint for user login that accepts credentials and returns a token.",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 2,
        "action": "Open the contact book",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/contactservice/contacts/account/{accountId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The user opens their contact book, which corresponds to refreshing the list of contacts for the logged-in account. Handler H83 is explicitly marked with the UI action 'refresh_booking_contacts' on the 'client_ticket_book' page, matching the scenario step. It uses the accountId from the login token.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 3,
        "action": "Refresh the list of orders for high-speed (GaoTie/DongChe) trains",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh orders for high-speed (GaoTie/DongChe) trains. According to the twin selection rule, G/D train types use the base service (ts-order-service). Handler H153 is the refresh endpoint for the base order service, which matches the UI action for refreshing order lists.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:else"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 4,
        "action": "Refresh the list of orders for regular ('Other' type) trains",
        "edgeId": "ts-order-other-service->ts-common:REST_HTTP",
        "source": "ts-order-other-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderOtherService/orderOther/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-other-service:other.controller.OrderOtherController#queryOrdersForRefresh(other.entity.QueryInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh orders for regular ('Other' type) trains. According to the twin selection rule, G/D trains use the base service (ts-order-service) while other types use the variant service (ts-order-other-service). Therefore, the handler in ts-order-other-service is the correct choice.",
        "services": [
          "ts-common",
          "ts-order-other-service"
        ],
        "tables": [
          "ts-order-other-service.orders_other"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-other-service-orders_other",
          "ts-common",
          "ts-order-other-service"
        ],
        "activeEdges": [
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE"
        ]
      },
      {
        "step": 5,
        "action": "Refresh the list of orders filtered by the 'Paid' status",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": true,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null,
          "state": 1
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders filtered by 'Paid' status. Since the scenario involves both high-speed (G/D) and regular ('Other') trains, and the previous steps refreshed both separately, this step likely targets one of them or both. However, the UI action 'queryMyOrderList' sends requests to both services simultaneously (as noted in H137 and H153 candidates). The prompt asks for the ",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:then",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b138:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 6,
        "action": "Look up the luggage consignments registered on the account",
        "edgeId": "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE",
        "source": "ts-consign-service",
        "target": "ts-consign-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/consignservice/consigns/account/{id}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-consign-service:consign.controller.ConsignController#findByAccountId(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to look up luggage consignments registered on the account. Handler H74 (ConsignController#findByAccountId) is the specific UI endpoint for querying consignments by account ID, matching the action 'queryMyConsign' on the 'client_consign_list' page.",
        "services": [
          "ts-consign-service"
        ],
        "tables": [
          "ts-consign-mysql.consign_record"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-consign-mysql-consign_record",
          "ts-consign-service"
        ],
        "activeEdges": [
          "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE"
        ]
      }
    ]
  },
  {
    "id": "S1",
    "name": "S1: Бронирование скоростного поезда (еда, страховка, багаж)",
    "title": "Buying a high-speed train ticket with food on the train, insurance and luggage; paying from the account; collecting the ticket and boarding",
    "description": "A registered passenger logs in with a username and password. They search for high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou departing on 1 October 2026 and open the details of the first trip in the results. They look at the food menu offered on that trip. They open their contact book and take the first contact as the passenger. They book one first-class seat on that trip for this contact, adding food on the train (the first dish from the menu), assurance (insurance) of the first type and luggage consignment of 2 kg to a consignee. They refresh their list of orders, open the new order and check its price. They pay for the order from their internal account balance. They collect the ticket for the order and then enter the station (board the train) with it. Finally they look up the luggage consignment record and the assurance record of the order.",
    "steps": [
      {
        "step": 1,
        "action": "Log in with username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to log in with username and password, which corresponds to the login action in the web UI. Handler H55 (UserController#getToken) is the specific endpoint for user login, accepting username and password.",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 2,
        "action": "Search high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou departing on 1 October 2026",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trips/left",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#queryInfo(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Suzhou",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The user searches for high-speed (GaoTie/DongChe) trains, which corresponds to the base travel service side (ts-travel-service) as specified by the twin selection rule. The UI action for searching routes sends a POST to /api/v1/travelservice/trips/left.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 3,
        "action": "Open the details of the first trip found",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trip_detail",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "travelDate": "2026-10-01",
          "from": "Shanghai",
          "to": "Suzhou"
        },
        "expectedOutcome": "success",
        "reasoning": "The user wants to open the details of the first trip found in step 2. Step 2 searched for high-speed (GaoTie/DongChe) trains, which are handled by the base travel service (ts-travel-service). The handler for retrieving detailed trip information including tickets is POST /api/v1/travelservice/trip_detail. The request uses the tripId from the first result of step 2.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 4,
        "action": "View the food menu offered on this trip",
        "edgeId": "ts-food-service->ts-station-food-service:REST_HTTP",
        "source": "ts-food-service",
        "target": "ts-station-food-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/foodservice/foods/{date}/{startStation}/{endStation}/{tripId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-food-service:foodsearch.controller.FoodController#getAllFood(java.lang.String,java.lang.String,java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to view the food menu for the specific trip found in previous steps. Handler H105 is the UI-facing endpoint for getting food options for a specific trip, date, and route, which matches the action 'initFoodSelect' on the ticket booking page.",
        "services": [
          "ts-common",
          "ts-food-service",
          "ts-route-service",
          "ts-station-food-service",
          "ts-train-food-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-route-service.route",
          "ts-station-food-service.station_food_list",
          "ts-station-food-service.station_food_store",
          "ts-train-food-service.train_food",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@229:86",
          "foodsearch.service.FoodServiceImpl#getAllFood(java.lang.String,java.lang.String,java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b259:then",
          "travel.service.TravelServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b530:then",
          "travel.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b76:then",
          "travel.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b79:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else"
        ],
        "activeNodes": [
          "db-ts-route-service-route",
          "db-ts-station-food-service-station_food_list",
          "db-ts-station-food-service-station_food_store",
          "db-ts-train-food-service-train_food",
          "db-ts-travel-service-trip",
          "ts-common",
          "ts-food-service",
          "ts-route-service",
          "ts-station-food-service",
          "ts-train-food-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-food-service->ts-station-food-service:REST_HTTP",
          "ts-food-service->ts-train-food-service:REST_HTTP",
          "ts-food-service->ts-travel-service:REST_HTTP",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-station-food-service->db-ts-station-food-service-station_food_list:DATABASE",
          "ts-station-food-service->db-ts-station-food-service-station_food_store:DATABASE",
          "ts-train-food-service->db-ts-train-food-service-train_food:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-route-service:REST_HTTP"
        ]
      },
      {
        "step": 5,
        "action": "Open the contact book and take the first contact",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/contactservice/contacts/account/{accountId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The user needs to retrieve their personal contact list to select a passenger; the handler `findContactsByAccountId` is the specific UI endpoint for refreshing/loading contacts for the logged-in user on the ticket booking page.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 6,
        "action": "Book one first-class seat on the trip for this contact, with food on the train, assurance (insurance) of the first type and luggage consignment of 2 kg to a consignee",
        "edgeId": "ts-preserve-service->ts-consign-price-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-consign-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveservice/preserve",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-service:preserve.controller.PreserveController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Suzhou",
          "assurance": 1,
          "foodType": 1,
          "stationName": "",
          "storeName": "",
          "foodPrice": 0,
          "consigneeWeight": 2.0,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The user is booking a high-speed train (G/D type), which routes to the base preserve service (ts-preserve-service) according to the twin selection rule. The step involves booking a seat with food, insurance, and luggage, which matches the full payload of the PreserveController#preserve endpoint.",
        "services": [
          "ts-assurance-service",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-consign-price-service",
          "ts-consign-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-assurance-service.assurance",
          "ts-config-service.config",
          "ts-consign-mysql.consign_record",
          "ts-consign-price-service.consign_price",
          "ts-contacts-service.contacts",
          "ts-delivery-service.delivery",
          "ts-food-service.food_order",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-user-service.user"
        ],
        "rules": [
          "ELEMENT_CALLBACK:contains(m4)",
          "ENTRY",
          "R3:url_dispatch@320:70",
          "R3:url_dispatch@381:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b81:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "foodsearch.service.FoodServiceImpl#createFoodOrder(foodsearch.entity.FoodOrder,org.springframework.http.HttpHeaders)@b117:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b148:then",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b179:else",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b193:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-assurance-service-assurance",
          "db-ts-config-service-config",
          "db-ts-consign-mysql-consign_record",
          "db-ts-consign-price-service-consign_price",
          "db-ts-contacts-service-contacts",
          "db-ts-delivery-service-delivery",
          "db-ts-food-service-food_order",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-user-service-user",
          "ts-assurance-service",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-consign-price-service",
          "ts-consign-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-assurance-service->db-ts-assurance-service-assurance:DATABASE",
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-consign-price-service->db-ts-consign-price-service-consign_price:DATABASE",
          "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE",
          "ts-consign-service->ts-consign-price-service:REST_HTTP",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-delivery-service->db-ts-delivery-service-delivery:DATABASE",
          "ts-food-service->db-ts-food-service-food_order:DATABASE",
          "ts-food-service->ts-delivery-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-service->ts-assurance-service:REST_HTTP",
          "ts-preserve-service->ts-basic-service:REST_HTTP",
          "ts-preserve-service->ts-consign-service:REST_HTTP",
          "ts-preserve-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-service->ts-food-service:REST_HTTP",
          "ts-preserve-service->ts-order-service:REST_HTTP",
          "ts-preserve-service->ts-seat-service:REST_HTTP",
          "ts-preserve-service->ts-security-service:REST_HTTP",
          "ts-preserve-service->ts-travel-service:REST_HTTP",
          "ts-preserve-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 7,
        "action": "Refresh the list of orders",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null,
          "state": 0
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders. The scenario involves high-speed trains (GaoTie/DongChe), which map to the base order service (ts-order-service) according to the twin selection rule (G/D uses base). Candidate H153 is the correct handler for refreshing orders in the base service, as indicated by the UI action 'queryMyOrderList' on the ticket collect/enter station pages which triggers a",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:else"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 8,
        "action": "Open the new order",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/orderservice/order/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#getOrderById(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The user wants to open the details of the new order created in step 6. Since the booking was for a high-speed train (G/D type), the order resides in the base order service (ts-order-service). The specific action is to retrieve a single order by its ID, which corresponds to the getOrderById handler.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 9,
        "action": "Check the price of the order",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/orderservice/order/price/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#getOrderPrice(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to check the price of the order created in step 6. The candidate H147 (OrderController#getOrderPrice) is the specific handler for retrieving the price of an order by its ID. Since the scenario involves high-speed trains (G/D type), the base order service (ts-order-service) is the correct side to use, as indicated by the twin selection rule.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 10,
        "action": "Pay for the order from the internal account balance",
        "edgeId": "ts-inside-payment-service->ts-common:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to pay for the order from the internal account balance. Handler H113 (InsidePaymentController#pay) is the specific UI-handler for paying via the internal payment service, which matches the requirement to use the internal account balance. The other payment handlers (H151, H135) are for external/general payment flows and are not marked as UI handlers for this specific action, while H15",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-service-orders",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 11,
        "action": "Collect the ticket for the order",
        "edgeId": "ts-execute-service->ts-common:REST_HTTP",
        "source": "ts-execute-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/executeservice/execute/collected/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-execute-service:execute.controller.ExecuteControlller#collectTicket(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to collect the ticket for the order, which corresponds to the 'collectTicket' action in the UI. Handler H88 is the specific endpoint for collecting a ticket by orderId.",
        "services": [
          "ts-common",
          "ts-execute-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b95:then",
          "execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b95:then",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-execute-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-execute-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 12,
        "action": "Enter the station (board the train) with the order",
        "edgeId": "ts-execute-service->ts-common:REST_HTTP",
        "source": "ts-execute-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/executeservice/execute/execute/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-execute-service:execute.controller.ExecuteControlller#executeTicket(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to enter the station (board the train), which corresponds to the 'executeTicket' action in the execute service. The candidate H89 matches this action and is explicitly marked as the UI handler for 'enterStation'.",
        "services": [
          "ts-common",
          "ts-execute-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;execute.serivce.ExecuteServiceImpl#ticketExecute(java.lang.String,org.springframework.http.HttpHeaders)@b47:then",
          "execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b95:then",
          "execute.serivce.ExecuteServiceImpl#ticketExecute(java.lang.String,org.springframework.http.HttpHeaders)@b47:then",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-execute-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-execute-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 13,
        "action": "Look up the luggage consignment record of the order",
        "edgeId": "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE",
        "source": "ts-consign-service",
        "target": "ts-consign-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/consignservice/consigns/order/{id}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-consign-service:consign.controller.ConsignController#findByOrderId(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to look up the luggage consignment record for the order. Handler H76 (ConsignController#findByOrderId) is the specific endpoint for retrieving consignment records by order ID, which matches the requirement to look up the record associated with the order from previous steps.",
        "services": [
          "ts-consign-service"
        ],
        "tables": [
          "ts-consign-mysql.consign_record"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-consign-mysql-consign_record",
          "ts-consign-service"
        ],
        "activeEdges": [
          "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE"
        ]
      },
      {
        "step": 14,
        "action": "Look up the assurance (insurance) record of the order",
        "edgeId": "ts-assurance-service->db-ts-assurance-service-assurance:DATABASE",
        "source": "ts-assurance-service",
        "target": "ts-assurance-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/assuranceservice/assurance/orderid/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-assurance-service:assurance.controller.AssuranceController#findAssuranceByOrderId(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to look up the assurance record for the order. Handler H44 is the specific endpoint to find an assurance by its associated orderId, which matches the requirement. The orderId is available from the order created in step 6 and retrieved in step 8.",
        "services": [
          "ts-assurance-service"
        ],
        "tables": [
          "ts-assurance-service.assurance"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-assurance-service-assurance",
          "ts-assurance-service"
        ],
        "activeEdges": [
          "ts-assurance-service->db-ts-assurance-service-assurance:DATABASE"
        ]
      }
    ]
  },
  {
    "id": "S2",
    "name": "S2: Обычный поезд, отмена и пересадка на дешевое место",
    "title": "Buying a regular train ticket with station food and no insurance; paying and cancelling with a refund; a second order rebooked to a cheaper seat class",
    "description": "A registered passenger logs in. They search for regular trains (the 'Other' train type, not high-speed) from Shanghai to Nanjing departing on 1 October 2026 and open the details of the first trip in the results. They browse the food stores at Suzhou station. They open their contact book and take the first contact as the passenger. They book one first-class seat on that regular train for this contact with food from a station store, without assurance (insurance) and without luggage consignment. They refresh their list of orders, pay for the order from the internal account balance, ask how much would be refunded if the order were cancelled, and cancel the order. Then they book another first-class seat on the same regular train for the same contact with the same station food, refresh the orders, pay for the new order, and rebook this paid ticket to a second-class seat on the same regular train: the second-class ticket is cheaper, so the difference is refunded to the internal account balance.",
    "steps": [
      {
        "step": 1,
        "action": "Log in with username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to log in with username and password, which corresponds to the login action in the web UI. Handler H55 is the specific endpoint for user login that returns a token, matching the UI action described.",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 2,
        "action": "Search regular trains (the 'Other' train type, not high-speed) from Shanghai to Nanjing departing on 1 October 2026",
        "edgeId": "ts-travel2-service->ts-price-service:REST_HTTP",
        "source": "ts-travel2-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travel2service/trips/left",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel2-service:travel2.controller.Travel2Controller#queryInfo(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Nanjing",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The user searches for regular trains (train type 'Other', not G/D), which maps to the variant travel service ts-travel2-service. The UI action for searching routes with trainTypeSelected == 0 (Other) sends a POST to /api/v1/travel2service/trips/left.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-other-service.orders_other",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel2-service.trip2"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-other-service-orders_other",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel2-service-trip2",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 3,
        "action": "Open the details of the first trip found",
        "edgeId": "ts-travel2-service->ts-price-service:REST_HTTP",
        "source": "ts-travel2-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travel2service/trip_detail",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel2-service:travel2.controller.Travel2Controller#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "travelDate": "2026-10-01",
          "from": "Shanghai",
          "to": "Nanjing"
        },
        "expectedOutcome": "success",
        "reasoning": "The user is viewing details of a trip found in step 2, which used the 'Other' train type service (ts-travel2-service). The twin handler for getting trip details in ts-travel2-service is H243 (POST /api/v1/travel2service/trip_detail), which returns full detail info including tickets, matching the 'open details' action better than the simple retrieve (H248) which excludes ticket info.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-other-service.orders_other",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel2-service.trip2"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "travel2.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b217:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-other-service-orders_other",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel2-service-trip2",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 4,
        "action": "Browse the food stores at Suzhou station",
        "edgeId": "ts-station-food-service->db-ts-station-food-service-station_food_list:DATABASE",
        "source": "ts-station-food-service",
        "target": "ts-station-food-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/stationfoodservice/stationfoodstores",
        "relationType": "REST_HTTP",
        "handler": "method:ts-station-food-service:food.controller.StationFoodController#getFoodStoresByStationNames(java.util.List)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to browse food stores at Suzhou station. H198 is the handler for getting food stores by station name/ID, which matches the intent of browsing stores at a specific station. Although the candidate list marks it as 'ui: none', it is the correct backend service endpoint for this data retrieval action in the context of the scenario's flow (browsing available stores before selecting food).",
        "services": [
          "ts-station-food-service"
        ],
        "tables": [
          "ts-station-food-service.station_food_list",
          "ts-station-food-service.station_food_store"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-station-food-service-station_food_list",
          "db-ts-station-food-service-station_food_store",
          "ts-station-food-service"
        ],
        "activeEdges": [
          "ts-station-food-service->db-ts-station-food-service-station_food_list:DATABASE",
          "ts-station-food-service->db-ts-station-food-service-station_food_store:DATABASE"
        ]
      },
      {
        "step": 5,
        "action": "Open the contact book and take the first contact",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/contactservice/contacts/account/{accountId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step requires opening the contact book for the logged-in user, which corresponds to fetching contacts by the current account ID. Handler H83 is the UI-mapped endpoint for refreshing/finding contacts by account ID on the ticket booking page.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 6,
        "action": "Book one first-class seat on the regular train for this contact, with food from a station store, no assurance (insurance) and no luggage consignment",
        "edgeId": "ts-preserve-other-service->ts-price-service:REST_HTTP",
        "source": "ts-preserve-other-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveotherservice/preserveOther",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-other-service:preserveOther.controller.PreserveOtherController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Nanjing",
          "assurance": 0,
          "foodType": 2,
          "stationName": "Suzhou",
          "foodPrice": 0,
          "consigneeWeight": 0,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The step involves booking a ticket for a regular train (non-G/D type), which routes to the 'Other' service variant. The UI action for selecting a contact and confirming the booking on non-high-speed trains triggers the preserve endpoint in ts-preserve-other-service. This handler accepts the trip ID from step 3, the contact ID from step 5, and handles the food and seat selection internally.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-contacts-service.contacts",
          "ts-delivery-service.delivery",
          "ts-food-service.food_order",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel2-service.trip2",
          "ts-user-service.user"
        ],
        "rules": [
          "ELEMENT_CALLBACK:contains(m4)",
          "ENTRY",
          "R3:url_dispatch@382:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b82:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "foodsearch.service.FoodServiceImpl#createFoodOrder(foodsearch.entity.FoodOrder,org.springframework.http.HttpHeaders)@b117:else",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b151:then",
          "preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b196:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:else",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "travel2.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b217:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-contacts-service-contacts",
          "db-ts-delivery-service-delivery",
          "db-ts-food-service-food_order",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel2-service-trip2",
          "db-ts-user-service-user",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-delivery-service->db-ts-delivery-service-delivery:DATABASE",
          "ts-food-service->db-ts-food-service-food_order:DATABASE",
          "ts-food-service->ts-delivery-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-other-service->ts-basic-service:REST_HTTP",
          "ts-preserve-other-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-other-service->ts-food-service:REST_HTTP",
          "ts-preserve-other-service->ts-order-other-service:REST_HTTP",
          "ts-preserve-other-service->ts-seat-service:REST_HTTP",
          "ts-preserve-other-service->ts-security-service:REST_HTTP",
          "ts-preserve-other-service->ts-travel2-service:REST_HTTP",
          "ts-preserve-other-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 7,
        "action": "Refresh the list of orders",
        "edgeId": "ts-order-other-service->ts-common:REST_HTTP",
        "source": "ts-order-other-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderOtherService/orderOther/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-other-service:other.controller.OrderOtherController#queryOrdersForRefresh(other.entity.QueryInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders. The previous booking (step 6) was for a regular train ('Other' type), which is handled by the `ts-order-other-service`. Therefore, the refresh request must target the variant service (`orderOtherService`) to retrieve orders for non-G/D trains.",
        "services": [
          "ts-common",
          "ts-order-other-service"
        ],
        "tables": [
          "ts-order-other-service.orders_other"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-other-service-orders_other",
          "ts-common",
          "ts-order-other-service"
        ],
        "activeEdges": [
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE"
        ]
      },
      {
        "step": 8,
        "action": "Pay for the order from the internal account balance",
        "edgeId": "ts-inside-payment-service->ts-order-other-service:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-order-other-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The user is paying for an order using the internal account balance. The candidate H113 (InsidePaymentController#pay) is the UI-handler for paying orders via the internal payment service, which matches the action 'payMyOrder' on the order list page. The order was created in step 6 (preserveOther) and is a non-G/D train order (regular train), so it resides in the orderOtherService, but the payment逻辑",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-other-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-other-service.orders_other"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:else"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-other-service-orders_other",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-other-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-other-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE"
        ]
      },
      {
        "step": 9,
        "action": "Ask how much would be refunded if the order were cancelled",
        "edgeId": "ts-cancel-service->ts-order-other-service:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-order-other-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/cancelservice/cancel/refound/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-cancel-service:cancel.controller.CancelController#calculate(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to calculate the refund amount for a cancelled order, which corresponds to the 'calculate' action in the CancelService. Handler H60 is explicitly marked for the 'Cancel' button action on the order list page and its method name is 'calculate', matching the requirement to ask how much would be refunded.",
        "services": [
          "ts-cancel-service",
          "ts-common",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-other-service.orders_other",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b178:then",
          "R7;cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b182:else",
          "cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b160:else",
          "cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b182:else"
        ],
        "activeNodes": [
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "ts-cancel-service",
          "ts-common",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-cancel-service->ts-order-other-service:REST_HTTP",
          "ts-cancel-service->ts-order-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 10,
        "action": "Cancel the order",
        "edgeId": "ts-cancel-service->ts-order-other-service:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-order-other-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/cancelservice/cancel/{orderId}/{loginId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-cancel-service:cancel.controller.CancelController#cancelTicket(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to cancel the order. The previous steps (6-8) involved booking and paying for an order on a regular train (non-G/D type) via the 'Other' service side. The cancellation logic for tickets is handled by the CancelService, specifically the cancelTicket endpoint which processes the cancellation and refunds. Although H128 (deleteOrder in orderOtherService) exists, the UI action for 'Cancel",
        "services": [
          "ts-cancel-service",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b182:else",
          "R7;cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b105:then",
          "R7;cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b109:then",
          "cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b160:else",
          "cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b182:else",
          "cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b109:then",
          "cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b117:then",
          "cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b49:else"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "ts-cancel-service",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-cancel-service->ts-inside-payment-service:REST_HTTP",
          "ts-cancel-service->ts-order-other-service:REST_HTTP",
          "ts-cancel-service->ts-order-service:REST_HTTP",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 11,
        "action": "Book another first-class seat on the same regular train for the same contact with the same station food",
        "edgeId": "ts-preserve-other-service->ts-price-service:REST_HTTP",
        "source": "ts-preserve-other-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveotherservice/preserveOther",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-other-service:preserveOther.controller.PreserveOtherController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Nanjing",
          "assurance": 0,
          "foodType": 2,
          "stationName": "Suzhou",
          "foodPrice": 0,
          "consigneeWeight": 0,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to book a ticket for a regular train (non-G/D type), which maps to the 'Other' service variant. The UI action for booking tickets on non-high-speed trains is handled by PreserveOtherController#preserve, which creates the order, handles food, and manages the reservation process.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-contacts-service.contacts",
          "ts-delivery-service.delivery",
          "ts-food-service.food_order",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel2-service.trip2",
          "ts-user-service.user"
        ],
        "rules": [
          "ELEMENT_CALLBACK:contains(m4)",
          "ENTRY",
          "R3:url_dispatch@382:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b82:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "foodsearch.service.FoodServiceImpl#createFoodOrder(foodsearch.entity.FoodOrder,org.springframework.http.HttpHeaders)@b117:else",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b151:then",
          "preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b196:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:else",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "travel2.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b217:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-contacts-service-contacts",
          "db-ts-delivery-service-delivery",
          "db-ts-food-service-food_order",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel2-service-trip2",
          "db-ts-user-service-user",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-delivery-service->db-ts-delivery-service-delivery:DATABASE",
          "ts-food-service->db-ts-food-service-food_order:DATABASE",
          "ts-food-service->ts-delivery-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-other-service->ts-basic-service:REST_HTTP",
          "ts-preserve-other-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-other-service->ts-food-service:REST_HTTP",
          "ts-preserve-other-service->ts-order-other-service:REST_HTTP",
          "ts-preserve-other-service->ts-seat-service:REST_HTTP",
          "ts-preserve-other-service->ts-security-service:REST_HTTP",
          "ts-preserve-other-service->ts-travel2-service:REST_HTTP",
          "ts-preserve-other-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 12,
        "action": "Refresh the list of orders",
        "edgeId": "ts-order-other-service->ts-common:REST_HTTP",
        "source": "ts-order-other-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderOtherService/orderOther/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-other-service:other.controller.OrderOtherController#queryOrdersForRefresh(other.entity.QueryInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The user is refreshing their order list after booking a second ticket on a regular train (non-G/D type). Since the previous booking (step 11) was on a regular train, the orders are stored in the 'other' service variant. The UI action for refreshing orders on this service is POST /api/v1/orderOtherService/orderOther/refresh.",
        "services": [
          "ts-common",
          "ts-order-other-service"
        ],
        "tables": [
          "ts-order-other-service.orders_other"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-other-service-orders_other",
          "ts-common",
          "ts-order-other-service"
        ],
        "activeEdges": [
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE"
        ]
      },
      {
        "step": 13,
        "action": "Pay for the new order from the internal account balance",
        "edgeId": "ts-inside-payment-service->ts-order-other-service:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-order-other-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to pay for the new order from the internal account balance. This corresponds to the InsidePaymentController#pay handler, which processes payments using the internal balance for a specific order. The order was created in step 11, so the orderId from that step is required.",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-other-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-other-service.orders_other"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:else"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-other-service-orders_other",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-other-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-other-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE"
        ]
      },
      {
        "step": 14,
        "action": "Rebook the paid ticket to a second-class seat on the same regular train (the cheaper ticket: the difference is refunded to the internal balance)",
        "edgeId": "ts-rebook-service->ts-price-service:REST_HTTP",
        "source": "ts-rebook-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/rebookservice/rebook",
        "relationType": "REST_HTTP",
        "handler": "method:ts-rebook-service:rebook.controller.RebookController#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 3
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to rebook a paid ticket to a cheaper seat class, which triggers a refund of the difference. According to the handler details, when the new price is not higher than the old price (cheaper or equal), the `rebook` endpoint (H174) handles the rebooking and refunds the difference directly, whereas the `payDifference` endpoint (H173) is only for when the new price is higher. Since the step",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-inside-payment-service",
          "ts-order-other-service",
          "ts-price-service",
          "ts-rebook-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-inside-payment-service.inside_money",
          "ts-order-other-service.orders_other",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel2-service.trip2"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@309:89",
          "R3:url_dispatch@351:63",
          "R3:url_dispatch@393:79",
          "R3:url_dispatch@59:74",
          "R5:lombok_tostring",
          "R7:jackson_ctor",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;rebook.service.RebookServiceImpl#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)@b124:then",
          "R7;rebook.service.RebookServiceImpl#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)@b94:else",
          "cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b109:then",
          "cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b117:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b151:then",
          "rebook.service.RebookServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b426:else",
          "rebook.service.RebookServiceImpl#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)@b124:then",
          "rebook.service.RebookServiceImpl#updateOrder(edu.fudan.common.entity.Order,rebook.entity.RebookInfo,edu.fudan.common.entity.TripAllDetail,java.lang.String,org.springframework.http.HttpHeaders)@b202:else",
          "rebook.service.RebookServiceImpl#updateOrder(edu.fudan.common.entity.Order,rebook.entity.RebookInfo,edu.fudan.common.entity.TripAllDetail,java.lang.String,org.springframework.http.HttpHeaders)@b220:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:else",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "travel2.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b217:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-inside-payment-service-inside_money",
          "db-ts-order-other-service-orders_other",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel2-service-trip2",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-inside-payment-service",
          "ts-order-other-service",
          "ts-price-service",
          "ts-rebook-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-rebook-service->ts-inside-payment-service:REST_HTTP",
          "ts-rebook-service->ts-order-other-service:REST_HTTP",
          "ts-rebook-service->ts-route-service:REST_HTTP",
          "ts-rebook-service->ts-seat-service:REST_HTTP",
          "ts-rebook-service->ts-train-service:REST_HTTP",
          "ts-rebook-service->ts-travel2-service:REST_HTTP",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP"
        ]
      }
    ]
  },
  {
    "id": "S3",
    "name": "S3: Бронирование со станционной едой и пересадка",
    "title": "Family trip on a high-speed train: two passengers, a new contact, station food, assurance and a small consignment; paying for both orders",
    "description": "A registered passenger logs in and searches for high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou departing on 1 October 2026, opens the details of the first trip found and browses the food stores at Suzhou station. They open their contact book, take the first contact and also add a new contact (a companion with an ID card). They book a first-class seat on that trip for the first contact with food from a station store, assurance (insurance) of the first type and a luggage consignment of only 0.5 kg to a consignee; then they book a second-class seat on the same trip for the new contact — without food, assurance or consignment. They refresh the list of orders, open both new orders and pay for both from the internal account balance. Finally they check what a 0.5 kg consignment within the region costs and look at the list of assurance types.",
    "steps": [
      {
        "step": 1,
        "action": "Log in with username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to log in with username and password, which corresponds to the login action in the web UI. Handler H55 (UserController#getToken) is the specific endpoint for user login, accepting username and password (and optionally a verification code).",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 2,
        "action": "Search high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou departing on 1 October 2026",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trips/left",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#queryInfo(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Suzhou",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The user searches for high-speed (GaoTie/DongChe) trains, which corresponds to the 'base' side of the travel services. According to the handler descriptions, H234 (ts-travel-service) is the base side handling GaoTie/DongChe train types, while H247 is for other types. The UI action 'searchRouteList' sends to H234 when trainTypeSelected is 0 or 1 (high-speed).",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 3,
        "action": "Open the details of the first trip found",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trip_detail",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "travelDate": "2026-10-01",
          "from": "Shanghai",
          "to": "Suzhou"
        },
        "expectedOutcome": "success",
        "reasoning": "The user wants to open the details of the first trip found in step 2. Step 2 searched for high-speed (GaoTie/DongChe) trains, which are handled by the base travel service (ts-travel-service). The handler for retrieving detailed trip information including tickets is POST /api/v1/travelservice/trip_detail. Since the trip was found via the high-speed search, the base service side (H230) is the twin, ",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 4,
        "action": "Browse the food stores at Suzhou station",
        "edgeId": "ts-station-food-service->db-ts-station-food-service-station_food_list:DATABASE",
        "source": "ts-station-food-service",
        "target": "ts-station-food-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/stationfoodservice/stationfoodstores",
        "relationType": "REST_HTTP",
        "handler": "method:ts-station-food-service:food.controller.StationFoodController#getFoodStoresByStationNames(java.util.List)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to browse food stores at Suzhou station. H198 is the handler for getting food stores by station name/ID, which matches the intent of browsing stores at a specific station. Although the candidate description says 'none' for UI, it is the correct functional endpoint for retrieving stores associated with a station, and the station name 'Suzhou' is known from previous steps (step 2/3).",
        "services": [
          "ts-station-food-service"
        ],
        "tables": [
          "ts-station-food-service.station_food_list",
          "ts-station-food-service.station_food_store"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-station-food-service-station_food_list",
          "db-ts-station-food-service-station_food_store",
          "ts-station-food-service"
        ],
        "activeEdges": [
          "ts-station-food-service->db-ts-station-food-service-station_food_list:DATABASE",
          "ts-station-food-service->db-ts-station-food-service-station_food_store:DATABASE"
        ]
      },
      {
        "step": 5,
        "action": "Open the contact book and take the first contact",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/contactservice/contacts/account/{accountId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to open the contact book, which corresponds to retrieving the list of contacts for the current user. Handler H83 is the UI-mapped endpoint for refreshing/loading contacts by account ID, which matches the action of opening the contact book.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 6,
        "action": "Add a new contact (a companion with an ID card) to the contact book",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/contactservice/contacts",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#createNewContacts(contacts.entity.Contacts,?HttpHeaders)",
        "params": {
          "documentType": 1
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to add a new contact, which corresponds to the create action in the contacts service. Handler H80 is the UI-callable endpoint for creating a new contact for the logged-in user, matching the scenario's requirement to add a companion.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 7,
        "action": "Book a first-class seat on the trip for the first contact, with food from a station store, assurance (insurance) of the first type and a luggage consignment of 0.5 kg to a consignee",
        "edgeId": "ts-preserve-service->ts-consign-price-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-consign-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveservice/preserve",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-service:preserve.controller.PreserveController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Suzhou",
          "assurance": 1,
          "foodType": 2,
          "stationName": "Suzhou",
          "foodPrice": 0.0,
          "consigneeWeight": 0.5,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The step involves booking a ticket for a high-speed train (GaoTie/DongChe), which requires using the base preserve service (ts-preserve-service) as per the twin selection rule (G/D uses base). The request body includes details for food, assurance, and consignment, which are handled by the PreserveController#preserve endpoint.",
        "services": [
          "ts-assurance-service",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-consign-price-service",
          "ts-consign-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-assurance-service.assurance",
          "ts-config-service.config",
          "ts-consign-mysql.consign_record",
          "ts-consign-price-service.consign_price",
          "ts-contacts-service.contacts",
          "ts-delivery-service.delivery",
          "ts-food-service.food_order",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-user-service.user"
        ],
        "rules": [
          "ELEMENT_CALLBACK:contains(m4)",
          "ENTRY",
          "R3:url_dispatch@320:70",
          "R3:url_dispatch@381:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b81:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "foodsearch.service.FoodServiceImpl#createFoodOrder(foodsearch.entity.FoodOrder,org.springframework.http.HttpHeaders)@b117:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b148:then",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b179:else",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b193:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-assurance-service-assurance",
          "db-ts-config-service-config",
          "db-ts-consign-mysql-consign_record",
          "db-ts-consign-price-service-consign_price",
          "db-ts-contacts-service-contacts",
          "db-ts-delivery-service-delivery",
          "db-ts-food-service-food_order",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-user-service-user",
          "ts-assurance-service",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-consign-price-service",
          "ts-consign-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-assurance-service->db-ts-assurance-service-assurance:DATABASE",
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-consign-price-service->db-ts-consign-price-service-consign_price:DATABASE",
          "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE",
          "ts-consign-service->ts-consign-price-service:REST_HTTP",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-delivery-service->db-ts-delivery-service-delivery:DATABASE",
          "ts-food-service->db-ts-food-service-food_order:DATABASE",
          "ts-food-service->ts-delivery-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-service->ts-assurance-service:REST_HTTP",
          "ts-preserve-service->ts-basic-service:REST_HTTP",
          "ts-preserve-service->ts-consign-service:REST_HTTP",
          "ts-preserve-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-service->ts-food-service:REST_HTTP",
          "ts-preserve-service->ts-order-service:REST_HTTP",
          "ts-preserve-service->ts-seat-service:REST_HTTP",
          "ts-preserve-service->ts-security-service:REST_HTTP",
          "ts-preserve-service->ts-travel-service:REST_HTTP",
          "ts-preserve-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 8,
        "action": "Book a second-class seat on the same trip for the new contact, without food, assurance or consignment",
        "edgeId": "ts-preserve-service->ts-price-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveservice/preserve",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-service:preserve.controller.PreserveController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 3,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Suzhou",
          "assurance": 0,
          "foodType": 0,
          "foodPrice": 0.0,
          "consigneeWeight": 0.0,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The step books a second-class seat on the same high-speed (G/D) trip found in step 2, which requires using the base preserve service (ts-preserve-service) as per the twin selection rule for G/D trains. The request uses the trip details from step 3 and the new contact created in step 6.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-contacts-service.contacts",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-user-service.user"
        ],
        "rules": [
          "ELEMENT_CALLBACK:contains(m4)",
          "ENTRY",
          "R3:url_dispatch@381:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b81:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b148:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-contacts-service-contacts",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-user-service-user",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-service->ts-basic-service:REST_HTTP",
          "ts-preserve-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-service->ts-order-service:REST_HTTP",
          "ts-preserve-service->ts-seat-service:REST_HTTP",
          "ts-preserve-service->ts-security-service:REST_HTTP",
          "ts-preserve-service->ts-travel-service:REST_HTTP",
          "ts-preserve-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 9,
        "action": "Refresh the list of orders",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders. The scenario involves high-speed trains (GaoTie/DongChe), which use the base order service (ts-order-service) according to the twin selection rule. Handler H153 is the UI-mapped refresh endpoint for the base order service.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:else"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 10,
        "action": "Open the first new order",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/orderservice/order/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#getOrderById(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to open the first new order. Since the scenario involves high-speed trains (G/D), the order is stored in ts-order-service. The candidate H145 (findAllOrder) is marked as having no UI, but the step 'Open the first new order' implies retrieving a specific order by ID, which corresponds to the getOrderById handler. However, looking at the candidates, H146 (GET /api/v1/orderservice/order",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 11,
        "action": "Open the second new order",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/orderservice/order/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#getOrderById(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to open the second new order. Since the scenario involves high-speed trains (G/D), the base order service (ts-order-service) is used, as confirmed by the twin selection rule. The handler to retrieve a specific order by ID is OrderController#getOrderById.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 12,
        "action": "Pay for the first order from the internal account balance",
        "edgeId": "ts-inside-payment-service->ts-common:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to pay for the first order using the internal account balance. Handler H113 (InsidePaymentController#pay) is the specific UI handler for paying orders via the internal payment service, which matches the requirement to use the internal account balance. The order ID is derived from the first order created in step 7.",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-service-orders",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 13,
        "action": "Pay for the second order from the internal account balance",
        "edgeId": "ts-inside-payment-service->ts-common:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to pay for the second order using the internal account balance. Step 12 already demonstrated the use of the internal payment service for the first order; this step repeats the action for the second order. The handler InsidePaymentController#pay is the UI-facing endpoint for paying orders via internal balance, and since the trip is high-speed (G/D), the base order service is used, but",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-service-orders",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 14,
        "action": "Check what a 0.5 kg consignment within the region costs",
        "edgeId": "ts-consign-price-service->db-ts-consign-price-service-consign_price:DATABASE",
        "source": "ts-consign-price-service",
        "target": "ts-consign-price-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/consignpriceservice/consignprice/{weight}/{isWithinRegion}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-consign-price-service:consignprice.controller.ConsignPriceController#getPriceByWeightAndRegion(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to check the cost of a 0.5 kg consignment within the region, which directly maps to the handler that calculates consignment price by weight and region flag. No previous step's data is required for this lookup as it is a general price query based on the parameters provided in the step.",
        "services": [
          "ts-consign-price-service"
        ],
        "tables": [
          "ts-consign-price-service.consign_price"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-consign-price-service-consign_price",
          "ts-consign-price-service"
        ],
        "activeEdges": [
          "ts-consign-price-service->db-ts-consign-price-service-consign_price:DATABASE"
        ]
      },
      {
        "step": 15,
        "action": "Look at the list of assurance types",
        "edgeId": "",
        "source": "ts-assurance-service",
        "target": "ts-assurance-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/assuranceservice/assurances/types",
        "relationType": "REST_HTTP",
        "handler": "method:ts-assurance-service:assurance.controller.AssuranceController#getAllAssuranceType(org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to look at the list of assurance types, which corresponds directly to the UI action 'getAssuranceType' on the 'client_ticket_book' page. Handler H45 is explicitly marked with this UI action and retrieves all assurance types.",
        "services": [
          "ts-assurance-service"
        ],
        "tables": [],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@320:70"
        ],
        "activeNodes": [
          "ts-assurance-service"
        ],
        "activeEdges": []
      }
    ]
  },
  {
    "id": "S4",
    "name": "S4: Регистрация, вход и внешняя оплата",
    "title": "A newly registered passenger with an empty balance: booking with food on the train and assurance, external payment, cancelling the paid order with a refund",
    "description": "A new passenger registers an account (username, password, gender, ID document, e-mail) and logs in with it. Having no contacts yet, they add one (themselves). They search for high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou departing on 1 October 2026, open the details of the first trip found and view the food menu offered on it. They book a first-class seat on that trip for the new contact with food on the train and assurance (insurance) of the first type, without a consignment. They refresh their list of orders, open the new order and check its price. They pay for the order: the internal account balance of a new user is empty, so the payment is completed through the external payment channel. Then they ask how much would be refunded if the paid order were cancelled, cancel it (the refund goes back to the internal balance), and refresh the list of orders filtered by the 'Cancel' status.",
    "steps": [
      {
        "step": 1,
        "action": "Register a new passenger account (username, password, gender, ID document, e-mail)",
        "edgeId": "ts-user-service->ts-auth-service:REST_HTTP",
        "source": "ts-user-service",
        "target": "ts-auth-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/userservice/users/register",
        "relationType": "REST_HTTP",
        "handler": "method:ts-user-service:user.controller.UserController#registerUser(user.dto.UserDto,org.springframework.http.HttpHeaders)",
        "params": {
          "gender": 0,
          "documentType": 1
        },
        "expectedOutcome": "success",
        "reasoning": "The step requires registering a new passenger account, which is handled by the user registration endpoint. H254 is the specific handler for user registration in the ts-user-service, whereas H36 is for admin creation and H50 is an internal auth call not directly exposed to the UI for this action.",
        "services": [
          "ts-auth-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles",
          "ts-user-service.user"
        ],
        "rules": [
          "ENTRY",
          "R10:save_writes_collection(line 65)",
          "user.service.impl.UserServiceImpl#saveUser(user.dto.UserDto,?HttpHeaders)@b64:then"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "db-ts-user-service-user",
          "ts-auth-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE",
          "ts-user-service->db-ts-user-service-user:DATABASE",
          "ts-user-service->ts-auth-service:REST_HTTP"
        ]
      },
      {
        "step": 2,
        "action": "Log in with the new username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to log in with the new username and password. Handler H55 (UserController#getToken) is the specific endpoint for user login via the web UI, accepting username and password to generate a token.",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6",
          "user.service.impl.UserServiceImpl#saveUser(user.dto.UserDto,?HttpHeaders)@b64:then"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 3,
        "action": "Add a contact (the passenger themselves) to the empty contact book",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/contactservice/contacts",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#createNewContacts(contacts.entity.Contacts,?HttpHeaders)",
        "params": {
          "documentType": 1
        },
        "expectedOutcome": "success",
        "reasoning": "The step requires adding a new contact for the logged-in passenger. H80 (ContactsController#createNewContacts) is the UI-handler for creating contacts in the passenger booking flow, which matches the action of adding a contact to an empty book.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 4,
        "action": "Search high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou departing on 1 October 2026",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trips/left",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#queryInfo(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Suzhou",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The user searches for high-speed (GaoTie/DongChe) trains, which corresponds to the base travel service side (ts-travel-service) as specified by the twin selection rule. The UI action for searching routes sends a POST to /api/v1/travelservice/trips/left.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 5,
        "action": "Open the details of the first trip found",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trip_detail",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "travelDate": "2026-10-01",
          "from": "Shanghai",
          "to": "Suzhou"
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to open the details of the first trip found in step 4. Step 4 searched for high-speed (GaoTie/DongChe) trains, which are handled by the base travel service (ts-travel-service). The handler for retrieving detailed trip information including tickets is POST /api/v1/travelservice/trip_detail. The request uses the tripId from the first result of step 4.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 6,
        "action": "View the food menu offered on this trip",
        "edgeId": "ts-food-service->ts-station-food-service:REST_HTTP",
        "source": "ts-food-service",
        "target": "ts-station-food-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/foodservice/foods/{date}/{startStation}/{endStation}/{tripId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-food-service:foodsearch.controller.FoodController#getAllFood(java.lang.String,java.lang.String,java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to view the food menu for the trip found in previous steps. Handler H105 is the UI-facing endpoint for initializing food selection, taking the trip ID (from step 5) and other context to return the food list.",
        "services": [
          "ts-common",
          "ts-food-service",
          "ts-route-service",
          "ts-station-food-service",
          "ts-train-food-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-route-service.route",
          "ts-station-food-service.station_food_list",
          "ts-station-food-service.station_food_store",
          "ts-train-food-service.train_food",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@229:86",
          "foodsearch.service.FoodServiceImpl#getAllFood(java.lang.String,java.lang.String,java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b259:then",
          "travel.service.TravelServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b530:then",
          "travel.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b76:then",
          "travel.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b79:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else"
        ],
        "activeNodes": [
          "db-ts-route-service-route",
          "db-ts-station-food-service-station_food_list",
          "db-ts-station-food-service-station_food_store",
          "db-ts-train-food-service-train_food",
          "db-ts-travel-service-trip",
          "ts-common",
          "ts-food-service",
          "ts-route-service",
          "ts-station-food-service",
          "ts-train-food-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-food-service->ts-station-food-service:REST_HTTP",
          "ts-food-service->ts-train-food-service:REST_HTTP",
          "ts-food-service->ts-travel-service:REST_HTTP",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-station-food-service->db-ts-station-food-service-station_food_list:DATABASE",
          "ts-station-food-service->db-ts-station-food-service-station_food_store:DATABASE",
          "ts-train-food-service->db-ts-train-food-service-train_food:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-route-service:REST_HTTP"
        ]
      },
      {
        "step": 7,
        "action": "Book a first-class seat on the trip for the new contact, with food on the train and assurance (insurance) of the first type, without consignment",
        "edgeId": "ts-preserve-service->ts-price-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveservice/preserve",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-service:preserve.controller.PreserveController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Suzhou",
          "assurance": 1,
          "foodType": 1,
          "stationName": "",
          "storeName": "",
          "foodPrice": 0,
          "consigneeWeight": 0,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The step involves booking a ticket for a high-speed train (GaoTie/DongChe, type G or D) with food and assurance. According to the twin service rules, G/D trains use the base service (ts-preserve-service). The UI action for booking with these options maps to the preserve endpoint which handles assurance, food, and order creation.",
        "services": [
          "ts-assurance-service",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-assurance-service.assurance",
          "ts-config-service.config",
          "ts-contacts-service.contacts",
          "ts-delivery-service.delivery",
          "ts-food-service.food_order",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-user-service.user"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@320:70",
          "R3:url_dispatch@381:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b81:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "foodsearch.service.FoodServiceImpl#createFoodOrder(foodsearch.entity.FoodOrder,org.springframework.http.HttpHeaders)@b117:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b148:then",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b179:else",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b193:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-assurance-service-assurance",
          "db-ts-config-service-config",
          "db-ts-contacts-service-contacts",
          "db-ts-delivery-service-delivery",
          "db-ts-food-service-food_order",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-user-service-user",
          "ts-assurance-service",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-delivery-service",
          "ts-food-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-assurance-service->db-ts-assurance-service-assurance:DATABASE",
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-delivery-service->db-ts-delivery-service-delivery:DATABASE",
          "ts-food-service->db-ts-food-service-food_order:DATABASE",
          "ts-food-service->ts-delivery-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-service->ts-assurance-service:REST_HTTP",
          "ts-preserve-service->ts-basic-service:REST_HTTP",
          "ts-preserve-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-service->ts-food-service:REST_HTTP",
          "ts-preserve-service->ts-order-service:REST_HTTP",
          "ts-preserve-service->ts-seat-service:REST_HTTP",
          "ts-preserve-service->ts-security-service:REST_HTTP",
          "ts-preserve-service->ts-travel-service:REST_HTTP",
          "ts-preserve-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 8,
        "action": "Refresh the list of orders",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null,
          "state": 0
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders. The previous booking (step 7) was for a high-speed train (GaoTie/DongChe, implied by 'high-speed' in step 4 and the use of ts-travel-service which handles G/D trains). The twin handler for refreshing orders for G/D trains is H153 in ts-order-service.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:else"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 9,
        "action": "Open the new order",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/orderservice/order/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#getOrderById(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to 'Open the new order', which implies retrieving the details of the specific order created in step 7. Since the booking was for a high-speed train (GaoTie/DongChe), the order resides in the base order service (ts-order-service). The handler `OrderController#getOrderById` (H146) is the correct endpoint to retrieve a single order by its ID, which is the result of the booking in step 7",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 10,
        "action": "Check the price of the order",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/orderservice/order/price/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#getOrderPrice(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to check the price of the order created in step 7. The candidate H147 (OrderController#getOrderPrice) is the specific handler for retrieving the price of an order by its ID. Since the scenario involves high-speed trains (GaoTie/DongChe), the base order service (ts-order-service) is the correct side to use, as indicated by the twin selection rule.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 11,
        "action": "Pay for the order: the internal balance is empty, so the payment is completed through the external payment channel",
        "edgeId": "ts-inside-payment-service->ts-common:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step requires paying for an order using an external payment channel because the internal balance is empty. H113 (InsidePaymentController#pay) is the UI-handler for paying orders and supports external payment (PaymentType O or E) when internal funds are insufficient, whereas H159 is not called by the UI. The request uses the order ID from the previous steps.",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service",
          "ts-payment-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-service.orders",
          "ts-payment-service.payment"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b118:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:then",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-service-orders",
          "db-ts-payment-service-payment",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service",
          "ts-payment-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-service:REST_HTTP",
          "ts-inside-payment-service->ts-payment-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-payment-service->db-ts-payment-service-payment:DATABASE"
        ]
      },
      {
        "step": 12,
        "action": "Ask how much would be refunded if the paid order were cancelled",
        "edgeId": "ts-cancel-service->ts-common:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/cancelservice/cancel/refound/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-cancel-service:cancel.controller.CancelController#calculate(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to calculate the refund amount for a cancelled order, which corresponds to the 'calculate' action in the cancel service. Handler H60 is explicitly mapped to calculating the refund for a given orderId.",
        "services": [
          "ts-cancel-service",
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b160:then",
          "R7;cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b164:else",
          "cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b164:else"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-cancel-service",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-cancel-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 13,
        "action": "Cancel the paid order (the refund goes back to the internal balance)",
        "edgeId": "ts-cancel-service->ts-common:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/cancelservice/cancel/{orderId}/{loginId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-cancel-service:cancel.controller.CancelController#cancelTicket(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to cancel the paid order, which corresponds to the `cancelTicket` action in the UI. Handler H61 (`CancelController#cancelTicket`) is the specific endpoint for cancelling a ticket, which handles the order status change and initiates the refund process (drawback money) as described. H60 is only for calculating the refund amount, not performing the cancellation.",
        "services": [
          "ts-cancel-service",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-order-service.orders",
          "ts-user-service.user"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b164:else",
          "R7;cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b49:then",
          "R7;cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b52:then",
          "cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b164:else",
          "cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b52:then",
          "cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b59:then",
          "cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b65:then",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-order-service-orders",
          "db-ts-user-service-user",
          "ts-cancel-service",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-cancel-service->ts-inside-payment-service:REST_HTTP",
          "ts-cancel-service->ts-order-service:REST_HTTP",
          "ts-cancel-service->ts-user-service:REST_HTTP",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 14,
        "action": "Refresh the list of orders filtered by the 'Cancel' status",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": true,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null,
          "state": 4
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders filtered by 'Cancel' status. The previous steps (booking a GaoTie/DongChe train) indicate the order is in the base `ts-order-service`. The handler `OrderController#queryOrdersForRefresh` (H153) is the correct twin for G/D trains and accepts a `state` parameter in the body to filter by status (CANCEL=4).",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:then",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b138:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      }
    ]
  },
  {
    "id": "S5",
    "name": "S5: Сложный маршрут и пересадка на обычный поезд",
    "title": "Advanced search: the cheapest, the quickest and the fewest-stops trips, a transfer via Suzhou; booking the cheapest trip, collecting the ticket and entering the station",
    "description": "A registered passenger logs in and uses the advanced search from Shanghai to Nanjing on 1 October 2026 three times: for the cheapest trips, for the quickest trips and for the trips with the fewest stops. They also ask for trips with a transfer at Suzhou (Shanghai — Suzhou — Nanjing) on the same date. The cheapest option turns out to be a regular train (the 'Other' train type, not high-speed): they open its details, take the first contact from their contact book and book a first-class seat on it without food, assurance or consignment. They refresh their list of orders, pay for the order from the internal account balance, collect the ticket and enter the station (board the train) with it.",
    "steps": [
      {
        "step": 1,
        "action": "Log in with username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to log in with username and password, which corresponds to the login action in the web UI. Handler H55 is the specific endpoint for user login that returns a token, matching the UI action described.",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 2,
        "action": "Advanced search: the cheapest trips from Shanghai to Nanjing on 1 October 2026",
        "edgeId": "ts-travel-plan-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-plan-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelplanservice/travelPlan/cheapest",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-plan-service:travelplan.controller.TravelPlanController#getByCheapest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Nanjing",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The step requests an advanced search for the cheapest trips, which maps directly to the TravelPlanController#getByCheapest handler marked with UI action 'adSearchPath' and condition selectType == 1. The request uses the login token from step 1 for authentication.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-plan-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-plan-service",
          "ts-travel-service",
          "ts-travel2-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-travel2-service.trip2"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@347:59",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;travelplan.service.TravelPlanServiceImpl#getCheapest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b96:then",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b530:then",
          "travel.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b76:then",
          "travel.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b79:then",
          "travel2.service.TravelServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b439:else",
          "travel2.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b57:else",
          "travelplan.service.TravelPlanServiceImpl#getCheapest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b96:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-travel2-service-trip2",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-plan-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-plan-service",
          "ts-travel-service",
          "ts-travel2-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-plan-service->ts-travel-service:REST_HTTP",
          "ts-route-plan-service->ts-travel2-service:REST_HTTP",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-plan-service->ts-route-plan-service:REST_HTTP",
          "ts-travel-plan-service->ts-seat-service:REST_HTTP",
          "ts-travel-plan-service->ts-train-service:REST_HTTP",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-route-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-route-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 3,
        "action": "Advanced search: the quickest trips from Shanghai to Nanjing on 1 October 2026",
        "edgeId": "ts-travel-plan-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-plan-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelplanservice/travelPlan/quickest",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-plan-service:travelplan.controller.TravelPlanController#getByQuickest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Nanjing",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The step requests an advanced search for the quickest trips, which maps directly to the TravelPlanController#getByQuickest handler. This handler is the specific UI endpoint for the 'quickest' search type in the advanced search flow, following the same pattern as step 2 (cheapest search).",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-plan-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-plan-service",
          "ts-travel-service",
          "ts-travel2-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-travel2-service.trip2"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@347:59",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;travelplan.service.TravelPlanServiceImpl#getQuickest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b144:then",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b530:then",
          "travel.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b76:then",
          "travel.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b79:then",
          "travel2.service.TravelServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b439:else",
          "travel2.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b57:else",
          "travelplan.service.TravelPlanServiceImpl#getCheapest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b96:then",
          "travelplan.service.TravelPlanServiceImpl#getQuickest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b144:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-travel2-service-trip2",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-plan-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-plan-service",
          "ts-travel-service",
          "ts-travel2-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-plan-service->ts-travel-service:REST_HTTP",
          "ts-route-plan-service->ts-travel2-service:REST_HTTP",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-plan-service->ts-route-plan-service:REST_HTTP",
          "ts-travel-plan-service->ts-seat-service:REST_HTTP",
          "ts-travel-plan-service->ts-train-service:REST_HTTP",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-route-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-route-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 4,
        "action": "Advanced search: the trips with the fewest stops from Shanghai to Nanjing on 1 October 2026",
        "edgeId": "ts-travel-plan-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-plan-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelplanservice/travelPlan/minStation",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-plan-service:travelplan.controller.TravelPlanController#getByMinStation(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Nanjing",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The step requests an advanced search for trips with the fewest stops, which corresponds to the 'minStation' search type in the TravelPlanService. Handler H221 is the specific endpoint for this operation, as indicated by its UI condition (selectType == 0) and method name.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-plan-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-plan-service",
          "ts-travel-service",
          "ts-travel2-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-route-service.route_stations",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-travel2-service.trip2"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(getRouteByStartAndEnd line 109: route.getStations())",
          "R3:url_dispatch@253:32",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;travelplan.service.TravelPlanServiceImpl#getMinStation(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b191:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "travel2.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b57:else",
          "travel2.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b217:else",
          "travelplan.service.TravelPlanServiceImpl#getCheapest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b96:then",
          "travelplan.service.TravelPlanServiceImpl#getMinStation(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b191:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-route-service-route_stations",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-travel2-service-trip2",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-plan-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-plan-service",
          "ts-travel-service",
          "ts-travel2-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-plan-service->ts-route-service:REST_HTTP",
          "ts-route-plan-service->ts-travel-service:REST_HTTP",
          "ts-route-plan-service->ts-travel2-service:REST_HTTP",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-route-service->db-ts-route-service-route_stations:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-plan-service->ts-route-plan-service:REST_HTTP",
          "ts-travel-plan-service->ts-seat-service:REST_HTTP",
          "ts-travel-plan-service->ts-train-service:REST_HTTP",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 5,
        "action": "Ask for trips with a transfer at Suzhou (Shanghai — Suzhou — Nanjing) on 1 October 2026",
        "edgeId": "ts-travel-plan-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-plan-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelplanservice/travelPlan/transferResult",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-plan-service:travelplan.controller.TravelPlanController#getTransferResult(travelplan.entity.TransferTravelInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startStation": "Shanghai",
          "viaStation": "Suzhou",
          "endStation": "Nanjing",
          "travelDate": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks for trips with a transfer at Suzhou, which corresponds to the transfer search functionality. Handler H223 (TravelPlanController#getTransferResult) is the specific endpoint for searching transit/transfer routes, accepting start, via, and end stations.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-plan-service",
          "ts-travel-service",
          "ts-travel2-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-travel2-service.trip2"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-travel2-service-trip2",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-plan-service",
          "ts-travel-service",
          "ts-travel2-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-plan-service->ts-travel-service:REST_HTTP",
          "ts-travel-plan-service->ts-travel2-service:REST_HTTP",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP"
        ]
      },
      {
        "step": 6,
        "action": "Open the details of the cheapest trip found (a regular, 'Other'-type train)",
        "edgeId": "ts-travel2-service->ts-price-service:REST_HTTP",
        "source": "ts-travel2-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travel2service/trip_detail",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel2-service:travel2.controller.Travel2Controller#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "travelDate": "2026-10-01",
          "from": "Shanghai",
          "to": "Nanjing"
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to open details of the cheapest trip, which is identified as a regular 'Other'-type train. According to the twin service rules, 'Other' train types are handled by the ts-travel2-service variant. Therefore, the handler in ts-travel2-service for retrieving trip details is selected.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-other-service.orders_other",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel2-service.trip2"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@253:32",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel2.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b57:else",
          "travel2.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b217:else",
          "travelplan.service.TravelPlanServiceImpl#getCheapest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b96:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-other-service-orders_other",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel2-service-trip2",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 7,
        "action": "Open the contact book and take the first contact",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/contactservice/contacts/account/{accountId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to open the contact book, which corresponds to fetching the contacts associated with the logged-in user's account. Handler H83 is the UI-mapped endpoint for retrieving contacts by account ID, which matches the action of opening the contact list.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 8,
        "action": "Book a first-class seat on the cheapest (regular) trip for this contact, without food, assurance or consignment",
        "edgeId": "ts-preserve-other-service->ts-price-service:REST_HTTP",
        "source": "ts-preserve-other-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveotherservice/preserveOther",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-other-service:preserveOther.controller.PreserveOtherController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Nanjing",
          "assurance": 0,
          "foodType": 0,
          "foodPrice": 0.0,
          "consigneeWeight": 0.0,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The step involves booking a ticket for a regular train (non-G/D type), which routes to the 'Other' service variant. The candidate H162 (PreserveOtherController#preserveOther) is the UI handler for booking non-G/D trains, as indicated by its condition `!(tripType == 'G' || tripType == 'D')`. It uses the contact information retrieved in step 7.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-contacts-service.contacts",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel2-service.trip2",
          "ts-user-service.user"
        ],
        "rules": [
          "ELEMENT_CALLBACK:contains(m4)",
          "ENTRY",
          "R3:url_dispatch@253:32",
          "R3:url_dispatch@382:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b82:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "other.service.OrderOtherServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b55:then",
          "preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b151:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:else",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:else",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel2.service.TravelServiceImpl#getRouteByTripId(java.lang.String,org.springframework.http.HttpHeaders)@b57:else",
          "travel2.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b217:else",
          "travelplan.service.TravelPlanServiceImpl#getCheapest(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)@b96:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-contacts-service-contacts",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel2-service-trip2",
          "db-ts-user-service-user",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-other-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel2-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-other-service->ts-basic-service:REST_HTTP",
          "ts-preserve-other-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-other-service->ts-order-other-service:REST_HTTP",
          "ts-preserve-other-service->ts-seat-service:REST_HTTP",
          "ts-preserve-other-service->ts-security-service:REST_HTTP",
          "ts-preserve-other-service->ts-travel2-service:REST_HTTP",
          "ts-preserve-other-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel2-service->db-ts-travel2-service-trip2:DATABASE",
          "ts-travel2-service->ts-basic-service:REST_HTTP",
          "ts-travel2-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 9,
        "action": "Refresh the list of orders",
        "edgeId": "ts-order-other-service->ts-common:REST_HTTP",
        "source": "ts-order-other-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderOtherService/orderOther/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-other-service:other.controller.OrderOtherController#queryOrdersForRefresh(other.entity.QueryInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders. The previous booking (step 8) was for a regular ('Other') train type, which is handled by the ts-order-other-service variant. Therefore, the refresh request must target the variant service (H137) to retrieve orders for non-G/D trains.",
        "services": [
          "ts-common",
          "ts-order-other-service"
        ],
        "tables": [
          "ts-order-other-service.orders_other"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-other-service-orders_other",
          "ts-common",
          "ts-order-other-service"
        ],
        "activeEdges": [
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE"
        ]
      },
      {
        "step": 10,
        "action": "Pay for the order from the internal account balance",
        "edgeId": "ts-inside-payment-service->ts-order-other-service:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-order-other-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to pay for the order using the internal account balance. The candidate H113 (InsidePaymentController#pay) is the UI-handler for paying with the internal account, as indicated by its UI tag 'client_order_list, action payMyOrder'. The order was created in step 8 (a non-G/D train, hence 'Other' service), so the payment request targets that specific order.",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-other-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-other-service.orders_other"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:else"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-other-service-orders_other",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-other-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-other-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE"
        ]
      },
      {
        "step": 11,
        "action": "Collect the ticket for the order",
        "edgeId": "ts-execute-service->ts-common:REST_HTTP",
        "source": "ts-execute-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/executeservice/execute/collected/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-execute-service:execute.controller.ExecuteControlller#collectTicket(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to collect the ticket for the order, which corresponds to the 'collectTicket' action in the UI. The candidate H88 (ExecuteControlller#collectTicket) is the specific handler for this action, taking the orderId as a path variable. The order was created in step 8 and paid in step 10, so the orderId from those steps is used.",
        "services": [
          "ts-common",
          "ts-execute-service",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-other-service.orders_other",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b113:then",
          "execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b113:then",
          "execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b95:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:else"
        ],
        "activeNodes": [
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "ts-common",
          "ts-execute-service",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-execute-service->ts-order-other-service:REST_HTTP",
          "ts-execute-service->ts-order-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 12,
        "action": "Enter the station (board the train) with the order",
        "edgeId": "ts-execute-service->ts-common:REST_HTTP",
        "source": "ts-execute-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/executeservice/execute/execute/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-execute-service:execute.controller.ExecuteControlller#executeTicket(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to enter the station (board the train), which corresponds to the 'executeTicket' action in the execute service. The candidate H89 matches this action exactly, taking the orderId from the order created in previous steps.",
        "services": [
          "ts-common",
          "ts-execute-service",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-other-service.orders_other",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;execute.serivce.ExecuteServiceImpl#ticketExecute(java.lang.String,org.springframework.http.HttpHeaders)@b65:then",
          "execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b113:then",
          "execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b95:else",
          "execute.serivce.ExecuteServiceImpl#ticketExecute(java.lang.String,org.springframework.http.HttpHeaders)@b47:else",
          "execute.serivce.ExecuteServiceImpl#ticketExecute(java.lang.String,org.springframework.http.HttpHeaders)@b65:then",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:else"
        ],
        "activeNodes": [
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "ts-common",
          "ts-execute-service",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-execute-service->ts-order-other-service:REST_HTTP",
          "ts-execute-service->ts-order-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      }
    ]
  },
  {
    "id": "S6",
    "name": "S6: Админ-операции (маршруты, поезда, цены, конфиги)",
    "title": "An administrator opens a new high-speed trip and a passenger is the first to buy a ticket on it",
    "description": "An administrator logs in to the admin console. They add a new station Ning Bo (stay time 5 minutes), a new train type GaoTieSix (100 second-class and 30 first-class seats, average speed 300), a new route Shanghai — Suzhou — Ning Bo (distances 0, 100 and 250), a price configuration for GaoTieSix on this route (basic rate 0.5, first-class rate 1.2) and a new high-speed trip G9101 of type GaoTieSix on this route from Shanghai via Suzhou to Ning Bo (departure 09:00, arrival 12:00). Then a registered passenger logs in, searches for high-speed (GaoTie/DongChe) trains from Shanghai to Ning Bo departing on 1 October 2026, opens the details of the new trip, takes the first contact from the contact book, books a first-class seat on it without food, assurance or consignment, refreshes the list of orders and pays for the order from the internal account balance. Finally the administrator opens the list of all orders in the system.",
    "steps": [
      {
        "step": 1,
        "action": "Log in to the admin console with the administrator's username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step requires logging in to the admin console, which corresponds to the login action on the adminlogin page. Handler H55 is the only candidate that serves the login functionality for both admin and client users, as indicated by its UI mapping to 'adminlogin'.",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 2,
        "action": "Add a new station Ning Bo with a stay time of 5 minutes",
        "edgeId": "ts-admin-basic-info-service->ts-station-service:REST_HTTP",
        "source": "ts-admin-basic-info-service",
        "target": "ts-station-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/adminbasicservice/adminbasic/stations",
        "relationType": "REST_HTTP",
        "handler": "method:ts-admin-basic-info-service:adminbasic.controller.AdminBasicInfoController#addStation(edu.fudan.common.entity.Station,org.springframework.http.HttpHeaders)",
        "params": {
          "name": "Ning Bo",
          "stayTime": 5
        },
        "expectedOutcome": "success",
        "reasoning": "The step requires adding a new station via the admin console, which maps to the admin basic info service handler for adding stations. Candidate H4 is the correct UI handler for this action.",
        "services": [
          "ts-admin-basic-info-service",
          "ts-station-service"
        ],
        "tables": [
          "ts-station-service.station"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-station-service-station",
          "ts-admin-basic-info-service",
          "ts-station-service"
        ],
        "activeEdges": [
          "ts-admin-basic-info-service->ts-station-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE"
        ]
      },
      {
        "step": 3,
        "action": "Add a new train type GaoTieSix with 100 second-class and 30 first-class seats and an average speed of 300",
        "edgeId": "ts-admin-basic-info-service->ts-train-service:REST_HTTP",
        "source": "ts-admin-basic-info-service",
        "target": "ts-train-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/adminbasicservice/adminbasic/trains",
        "relationType": "REST_HTTP",
        "handler": "method:ts-admin-basic-info-service:adminbasic.controller.AdminBasicInfoController#addTrain(edu.fudan.common.entity.TrainType,org.springframework.http.HttpHeaders)",
        "params": {
          "name": "GaoTieSix",
          "economyClass": 100,
          "confortClass": 30,
          "averageSpeed": 300
        },
        "expectedOutcome": "success",
        "reasoning": "The step requires adding a new train type via the admin console, which maps to the AdminBasicInfoController#addTrain handler. This handler is designed for admin operations on train types and matches the UI action for adding a train.",
        "services": [
          "ts-admin-basic-info-service",
          "ts-train-service"
        ],
        "tables": [
          "ts-train-service.train_type"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-train-service-train_type",
          "ts-admin-basic-info-service",
          "ts-train-service"
        ],
        "activeEdges": [
          "ts-admin-basic-info-service->ts-train-service:REST_HTTP",
          "ts-train-service->db-ts-train-service-train_type:DATABASE"
        ]
      },
      {
        "step": 4,
        "action": "Add a new route Shanghai — Suzhou — Ning Bo with distances 0, 100 and 250",
        "edgeId": "ts-admin-route-service->ts-common:REST_HTTP",
        "source": "ts-admin-route-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/adminrouteservice/adminroute",
        "relationType": "REST_HTTP",
        "handler": "method:ts-admin-route-service:adminroute.controller.AdminRouteController#addRoute(edu.fudan.common.entity.RouteInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startStation": "Shanghai",
          "endStation": "Ning Bo",
          "stationList": "Shanghai,Suzhou,Ning Bo",
          "distanceList": "0,100,250"
        },
        "expectedOutcome": "success",
        "reasoning": "The step requires adding a new route, which corresponds to the admin route creation endpoint. H27 is the specific admin handler for adding routes, taking the station list and distances as input.",
        "services": [
          "ts-admin-route-service",
          "ts-common",
          "ts-route-service",
          "ts-station-service"
        ],
        "tables": [
          "ts-route-service.route",
          "ts-route-service.route_distances",
          "ts-route-service.route_stations",
          "ts-station-service.station"
        ],
        "rules": [
          "ENTRY",
          "R10:save_writes_collection(line 63)",
          "route.service.RouteServiceImpl#createAndModify(route.entity.RouteInfo,org.springframework.http.HttpHeaders)@b49:else"
        ],
        "activeNodes": [
          "db-ts-route-service-route",
          "db-ts-route-service-route_distances",
          "db-ts-route-service-route_stations",
          "db-ts-station-service-station",
          "ts-admin-route-service",
          "ts-common",
          "ts-route-service",
          "ts-station-service"
        ],
        "activeEdges": [
          "ts-admin-route-service->ts-route-service:REST_HTTP",
          "ts-admin-route-service->ts-station-service:REST_HTTP",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-route-service->db-ts-route-service-route_distances:DATABASE",
          "ts-route-service->db-ts-route-service-route_stations:DATABASE",
          "ts-station-service->db-ts-station-service-station:DATABASE"
        ]
      },
      {
        "step": 5,
        "action": "Add a price configuration for train type GaoTieSix on the new route: basic rate 0.5, first-class rate 1.2",
        "edgeId": "ts-admin-basic-info-service->ts-price-service:REST_HTTP",
        "source": "ts-admin-basic-info-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/adminbasicservice/adminbasic/prices",
        "relationType": "REST_HTTP",
        "handler": "method:ts-admin-basic-info-service:adminbasic.controller.AdminBasicInfoController#addPrice(adminbasic.entity.PriceInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "trainType": "GaoTieSix",
          "basicPriceRate": 0.5,
          "firstClassPriceRate": 1.2
        },
        "expectedOutcome": "success",
        "reasoning": "The step requires an administrator to add a new price configuration, which corresponds to the admin console action for adding prices. Handler H3 is the specific admin UI endpoint for adding a price configuration, matching the context of previous admin setup steps.",
        "services": [
          "ts-admin-basic-info-service",
          "ts-price-service"
        ],
        "tables": [
          "ts-price-service.price_config"
        ],
        "rules": [
          "ENTRY",
          "price.service.PriceServiceImpl#createNewPriceConfig(price.entity.PriceConfig,org.springframework.http.HttpHeaders)@b33:else"
        ],
        "activeNodes": [
          "db-ts-price-service-price_config",
          "ts-admin-basic-info-service",
          "ts-price-service"
        ],
        "activeEdges": [
          "ts-admin-basic-info-service->ts-price-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE"
        ]
      },
      {
        "step": 6,
        "action": "Add a new high-speed trip G9101 of type GaoTieSix on the new route from Shanghai via Suzhou to Ning Bo, departing 09:00 and arriving 12:00",
        "edgeId": "ts-admin-travel-service->ts-common:REST_HTTP",
        "source": "ts-admin-travel-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/admintravelservice/admintravel",
        "relationType": "REST_HTTP",
        "handler": "method:ts-admin-travel-service:admintravel.controller.AdminTravelController#addTravel(edu.fudan.common.entity.TravelInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "tripId": "G9101",
          "trainTypeName": "GaoTieSix",
          "startStationName": "Shanghai",
          "stationsName": "Shanghai,Suzhou,Ning Bo",
          "terminalStationName": "Ning Bo",
          "startTime": "09:00",
          "endTime": "12:00"
        },
        "expectedOutcome": "success",
        "reasoning": "The step requires adding a new trip, which is an administrative action handled by the admin travel service. The train type is 'GaoTieSix' (G-type), so the base travel service (ts-travel-service) is the correct backend, but the request originates from the admin console, so the admin handler H31 is the correct entry point. The request uses the route ID created in step 4 and the train type ID created",
        "services": [
          "ts-admin-travel-service",
          "ts-common",
          "ts-route-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@107:52",
          "admintravel.service.AdminTravelServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b280:else",
          "travel.service.TravelServiceImpl#create(edu.fudan.common.entity.TravelInfo,org.springframework.http.HttpHeaders)@b61:then"
        ],
        "activeNodes": [
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-admin-travel-service",
          "ts-common",
          "ts-route-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-admin-travel-service->ts-route-service:REST_HTTP",
          "ts-admin-travel-service->ts-station-service:REST_HTTP",
          "ts-admin-travel-service->ts-train-service:REST_HTTP",
          "ts-admin-travel-service->ts-travel-service:REST_HTTP",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE"
        ]
      },
      {
        "step": 7,
        "action": "Log in as a passenger with username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step requires logging in as a passenger, which corresponds to the standard user login endpoint. Handler H55 is the designated UI handler for user login (client_login page).",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 8,
        "action": "Search high-speed (GaoTie/DongChe) trains from Shanghai to Ning Bo departing on 1 October 2026",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trips/left",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#queryInfo(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Ning Bo",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The user searches for high-speed (GaoTie/DongChe) trains, which corresponds to the base travel service side for GaoTie/DongChe train types. The UI action 'searchRouteList' with trainTypeSelected == 0 (high-speed) triggers the query on ts-travel-service.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7;ENTRY",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#create(edu.fudan.common.entity.TravelInfo,org.springframework.http.HttpHeaders)@b61:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 9,
        "action": "Open the details of the new trip found",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trip_detail",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "travelDate": "2026-10-01",
          "from": "Shanghai",
          "to": "Ning Bo"
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to open the details of the new trip found in step 8. The trip G9101 is of type 'GaoTieSix' (a G-type high-speed train), which maps to the base travel service (ts-travel-service) according to the twin selection rule. Handler H230 (POST /api/v1/travelservice/trip_detail) is the correct endpoint to retrieve detailed trip information including remaining tickets, and it requires the trip,",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7;ENTRY",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#create(edu.fudan.common.entity.TravelInfo,org.springframework.http.HttpHeaders)@b61:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 10,
        "action": "Open the contact book and take the first contact",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/contactservice/contacts/account/{accountId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to open the contact book for the logged-in passenger, which corresponds to fetching contacts by the current user's account ID. Handler H83 is the UI-facing endpoint for this action, as indicated by its UI mapping to 'refresh_booking_contacts'.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 11,
        "action": "Book a first-class seat on the new trip for this contact, without food, assurance or consignment",
        "edgeId": "ts-preserve-service->ts-price-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveservice/preserve",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-service:preserve.controller.PreserveController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Ning Bo",
          "assurance": 0,
          "foodType": 0,
          "foodPrice": 0,
          "consigneeWeight": 0,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The step involves booking a ticket for a high-speed train (G9101, type GaoTieSix, type G), which requires using the base order service. The UI action 'Select' on the booking page for G/D trains triggers POST /api/v1/preserveservice/preserve. This handler uses the trip ID from step 9, the contact ID from step 10, and the account ID from step 7.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-contacts-service.contacts",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-user-service.user"
        ],
        "rules": [
          "ELEMENT_CALLBACK:contains(m4)",
          "ENTRY",
          "R3:url_dispatch@381:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b81:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b148:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#create(edu.fudan.common.entity.TravelInfo,org.springframework.http.HttpHeaders)@b61:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-contacts-service-contacts",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-user-service-user",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-contacts-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-service->ts-basic-service:REST_HTTP",
          "ts-preserve-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-service->ts-order-service:REST_HTTP",
          "ts-preserve-service->ts-seat-service:REST_HTTP",
          "ts-preserve-service->ts-security-service:REST_HTTP",
          "ts-preserve-service->ts-travel-service:REST_HTTP",
          "ts-preserve-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 12,
        "action": "Refresh the list of orders",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders, which corresponds to the 'queryMyOrderList' UI action. Since the order was just created for a high-speed train (G9101, type G), the base order service (ts-order-service) handles G/D trains, so H153 is the correct handler.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:else"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 13,
        "action": "Pay for the order from the internal account balance",
        "edgeId": "ts-inside-payment-service->ts-common:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to pay for the order from the internal account balance. Handler H113 (InsidePaymentController#pay) is the UI-mapped handler for paying orders using the internal payment service, which matches the action 'payMyOrder' on the order list page.",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-service-orders",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 14,
        "action": "As the administrator, open the list of all orders in the system",
        "edgeId": "ts-admin-order-service->ts-order-other-service:REST_HTTP",
        "source": "ts-admin-order-service",
        "target": "ts-order-other-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/adminorderservice/adminorder",
        "relationType": "REST_HTTP",
        "handler": "method:ts-admin-order-service:adminorder.controller.AdminOrderController#getAllOrders(org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks the administrator to open the list of all orders in the system, which corresponds to the admin console action for loading order records. Handler H24 is the specific admin endpoint for retrieving all orders, marked with UI action 'loadRecordList' on the admin page.",
        "services": [
          "ts-admin-order-service",
          "ts-common",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-other-service.orders_other",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "ts-admin-order-service",
          "ts-common",
          "ts-order-other-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-admin-order-service->ts-order-other-service:REST_HTTP",
          "ts-admin-order-service->ts-order-service:REST_HTTP",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      }
    ]
  },
  {
    "id": "S7",
    "name": "S7: Пересадка с доплатой и отказ при возврате",
    "title": "After collecting the ticket: refused cancellation and rebooking, changing the consignee, orders filtered by dates",
    "description": "A registered passenger logs in, searches for high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou departing on 1 October 2026, takes the first contact from the contact book and books a first-class seat on the first trip found with a luggage consignment of 3 kg to a consignee, without food or assurance. They refresh the list of orders, pay for the order from the internal account balance and collect the ticket. Then they ask how much would be refunded for this order and try to cancel it — the system refuses, because the ticket has already been collected; they try to rebook the order onto the second high-speed trip found — the system refuses for the same reason. They look up the luggage consignment of the order and change the consignee's name and phone number. Finally they refresh the list of orders filtered by travel date (September — December 2026) and then filtered by purchase date (today).",
    "steps": [
      {
        "step": 1,
        "action": "Log in with username and password",
        "edgeId": "ts-auth-service->ts-common:REST_HTTP",
        "source": "ts-auth-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/users/login",
        "relationType": "REST_HTTP",
        "handler": "method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to log in with username and password, which corresponds to the login action in the web UI. Handler H55 is the specific endpoint for user login that accepts credentials and returns a token.",
        "services": [
          "ts-auth-service",
          "ts-common"
        ],
        "tables": [
          "ts-auth-service.auth_user",
          "ts-auth-service.user_roles"
        ],
        "rules": [
          "ENTRY",
          "R10:loaded(createToken line 32: user.getRoles())",
          "spring_security",
          "spring_security:R6"
        ],
        "activeNodes": [
          "db-ts-auth-service-auth_user",
          "db-ts-auth-service-user_roles",
          "ts-auth-service",
          "ts-common"
        ],
        "activeEdges": [
          "ts-auth-service->db-ts-auth-service-auth_user:DATABASE",
          "ts-auth-service->db-ts-auth-service-user_roles:DATABASE"
        ]
      },
      {
        "step": 2,
        "action": "Search high-speed (GaoTie/DongChe) trains from Shanghai to Suzhou departing on 1 October 2026",
        "edgeId": "ts-travel-service->ts-price-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trips/left",
        "relationType": "REST_HTTP",
        "handler": "method:ts-travel-service:travel.controller.TravelController#queryInfo(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "startPlace": "Shanghai",
          "endPlace": "Suzhou",
          "departureTime": "2026-10-01"
        },
        "expectedOutcome": "success",
        "reasoning": "The user searches for high-speed (GaoTie/DongChe) trains, which corresponds to the base travel service side (ts-travel-service) as specified by the twin selection rule. The action is a standard route search for available trips.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip"
        ],
        "rules": [
          "ENTRY",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "fdse.microservice.service.BasicServiceImpl#getRoutesByRouteIds(java.util.List,org.springframework.http.HttpHeaders)@b413:else",
          "fdse.microservice.service.BasicServiceImpl#queryPriceConfigByRouteIdsAndTrainTypes(java.util.List,org.springframework.http.HttpHeaders)@b469:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-order-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP"
        ]
      },
      {
        "step": 3,
        "action": "Open the contact book and take the first contact",
        "edgeId": "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
        "source": "ts-contacts-service",
        "target": "ts-contacts-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/contactservice/contacts/account/{accountId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-contacts-service:contacts.controller.ContactsController#findContactsByAccountId(java.lang.String,?HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step requires opening the contact book for the logged-in user, which corresponds to fetching contacts by the user's account ID. Handler H83 is the specific UI endpoint for refreshing/finding contacts by account ID.",
        "services": [
          "ts-contacts-service"
        ],
        "tables": [
          "ts-contacts-service.contacts"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-contacts-service-contacts",
          "ts-contacts-service"
        ],
        "activeEdges": [
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE"
        ]
      },
      {
        "step": 4,
        "action": "Book a first-class seat on the first trip found for this contact, with a luggage consignment of 3 kg to a consignee, without food or assurance",
        "edgeId": "ts-preserve-service->ts-price-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/preserveservice/preserve",
        "relationType": "REST_HTTP",
        "handler": "method:ts-preserve-service:preserve.controller.PreserveController#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01",
          "from": "Shanghai",
          "to": "Suzhou",
          "assurance": 0,
          "foodType": 0,
          "consigneeWeight": 3.0,
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The user is booking a ticket for a high-speed train (G/D type) found in step 2, using the contact from step 3. The UI sends a POST to the preserve service for G/D trains, which handles the order creation, seat dispatch, and consignment setup in one go.",
        "services": [
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-consign-price-service",
          "ts-consign-service",
          "ts-contacts-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "tables": [
          "ts-config-service.config",
          "ts-consign-mysql.consign_record",
          "ts-consign-price-service.consign_price",
          "ts-contacts-service.contacts",
          "ts-order-other-service.orders_other",
          "ts-order-service.orders",
          "ts-price-service.price_config",
          "ts-route-service.route",
          "ts-security-service.security_config",
          "ts-station-service.station",
          "ts-train-service.train_type",
          "ts-travel-service.trip",
          "ts-user-service.user"
        ],
        "rules": [
          "ELEMENT_CALLBACK:contains(m4)",
          "ENTRY",
          "R3:url_dispatch@381:79",
          "R5:lombok_tostring",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b81:else",
          "edu.fudan.common.entity.SeatClass#getNameByCode(int)@b64:then",
          "fdse.microservice.service.BasicServiceImpl#getRouteByRouteId(java.lang.String,org.springframework.http.HttpHeaders)@b433:else",
          "order.service.OrderServiceImpl#getSoldTickets(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b57:then",
          "preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)@b148:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b53:then",
          "seat.service.SeatServiceImpl#distributeSeat(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b97:then",
          "seat.service.SeatServiceImpl#getLeftTicketOfInterval(edu.fudan.common.entity.Seat,org.springframework.http.HttpHeaders)@b138:then",
          "travel.service.TravelServiceImpl#getTripAllDetailInfo(edu.fudan.common.entity.TripAllDetailInfo,org.springframework.http.HttpHeaders)@b300:else",
          "unresolved_receiver"
        ],
        "activeNodes": [
          "db-ts-config-service-config",
          "db-ts-consign-mysql-consign_record",
          "db-ts-consign-price-service-consign_price",
          "db-ts-contacts-service-contacts",
          "db-ts-order-other-service-orders_other",
          "db-ts-order-service-orders",
          "db-ts-price-service-price_config",
          "db-ts-route-service-route",
          "db-ts-security-service-security_config",
          "db-ts-station-service-station",
          "db-ts-train-service-train_type",
          "db-ts-travel-service-trip",
          "db-ts-user-service-user",
          "ts-basic-service",
          "ts-common",
          "ts-config-service",
          "ts-consign-price-service",
          "ts-consign-service",
          "ts-contacts-service",
          "ts-order-other-service",
          "ts-order-service",
          "ts-preserve-service",
          "ts-price-service",
          "ts-route-service",
          "ts-seat-service",
          "ts-security-service",
          "ts-station-service",
          "ts-train-service",
          "ts-travel-service",
          "ts-user-service"
        ],
        "activeEdges": [
          "ts-basic-service->ts-price-service:REST_HTTP",
          "ts-basic-service->ts-route-service:REST_HTTP",
          "ts-basic-service->ts-station-service:REST_HTTP",
          "ts-basic-service->ts-train-service:REST_HTTP",
          "ts-config-service->db-ts-config-service-config:DATABASE",
          "ts-consign-price-service->db-ts-consign-price-service-consign_price:DATABASE",
          "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE",
          "ts-consign-service->ts-consign-price-service:REST_HTTP",
          "ts-contacts-service->db-ts-contacts-service-contacts:DATABASE",
          "ts-order-other-service->db-ts-order-other-service-orders_other:DATABASE",
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-preserve-service->ts-basic-service:REST_HTTP",
          "ts-preserve-service->ts-consign-service:REST_HTTP",
          "ts-preserve-service->ts-contacts-service:REST_HTTP",
          "ts-preserve-service->ts-order-service:REST_HTTP",
          "ts-preserve-service->ts-seat-service:REST_HTTP",
          "ts-preserve-service->ts-security-service:REST_HTTP",
          "ts-preserve-service->ts-travel-service:REST_HTTP",
          "ts-preserve-service->ts-user-service:REST_HTTP",
          "ts-price-service->db-ts-price-service-price_config:DATABASE",
          "ts-route-service->db-ts-route-service-route:DATABASE",
          "ts-seat-service->ts-config-service:REST_HTTP",
          "ts-seat-service->ts-order-service:REST_HTTP",
          "ts-security-service->db-ts-security-service-security_config:DATABASE",
          "ts-security-service->ts-order-other-service:REST_HTTP",
          "ts-security-service->ts-order-service:REST_HTTP",
          "ts-station-service->db-ts-station-service-station:DATABASE",
          "ts-train-service->db-ts-train-service-train_type:DATABASE",
          "ts-travel-service->db-ts-travel-service-trip:DATABASE",
          "ts-travel-service->ts-basic-service:REST_HTTP",
          "ts-travel-service->ts-seat-service:REST_HTTP",
          "ts-user-service->db-ts-user-service-user:DATABASE"
        ]
      },
      {
        "step": 5,
        "action": "Refresh the list of orders",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": false,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders. Since the order was booked on a high-speed train (GaoTie/DongChe) in step 4, the base order service (ts-order-service) handles G/D train orders. The UI action for refreshing orders on the ticket collection page maps to the refresh endpoint in the order service.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:else"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 6,
        "action": "Pay for the order from the internal account balance",
        "edgeId": "ts-inside-payment-service->ts-common:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment",
        "relationType": "REST_HTTP",
        "handler": "method:ts-inside-payment-service:inside_payment.controller.InsidePaymentController#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to pay for the order from the internal account balance. Handler H113 (InsidePaymentController#pay) is the UI-mapped endpoint for paying orders using the internal payment service, which matches the action 'payMyOrder' on the order list page.",
        "services": [
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-inside-payment-service.inside_money",
          "ts-inside-payment-service.inside_payment",
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b68:then",
          "inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)@b99:else",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-inside-payment-service-inside_money",
          "db-ts-inside-payment-service-inside_payment",
          "db-ts-order-service-orders",
          "ts-common",
          "ts-inside-payment-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_money:DATABASE",
          "ts-inside-payment-service->db-ts-inside-payment-service-inside_payment:DATABASE",
          "ts-inside-payment-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 7,
        "action": "Collect the ticket for the order",
        "edgeId": "ts-execute-service->ts-common:REST_HTTP",
        "source": "ts-execute-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/executeservice/execute/collected/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-execute-service:execute.controller.ExecuteControlller#collectTicket(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to collect the ticket for the order, which corresponds to the 'collectTicket' action in the UI. The candidate H88 is the specific handler for collecting tickets, taking the orderId as a path variable. The order was created in step 4 and paid in step 6, so the orderId from the order created in step 4 is used.",
        "services": [
          "ts-common",
          "ts-execute-service",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b95:then",
          "execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)@b95:then",
          "inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b335:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-execute-service",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-execute-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 8,
        "action": "Ask how much would be refunded for the collected order",
        "edgeId": "ts-cancel-service->ts-common:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/cancelservice/cancel/refound/{orderId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-cancel-service:cancel.controller.CancelController#calculate(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to calculate the refund amount for the collected order, which maps directly to the cancel service's calculate endpoint. Since the order was booked on a high-speed train (G/D type) in step 4, the order resides in ts-order-service, but the cancellation/refund logic is handled by the dedicated cancel service which queries the order data.",
        "services": [
          "ts-cancel-service",
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)@b160:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-cancel-service",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-cancel-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 9,
        "action": "Try to cancel the collected order (the system refuses)",
        "edgeId": "ts-cancel-service->ts-common:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-common",
        "httpMethod": "GET",
        "endpoint": "/api/v1/cancelservice/cancel/{orderId}/{loginId}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-cancel-service:cancel.controller.CancelController#cancelTicket(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "refused",
        "reasoning": "The step asks to cancel the collected order, which corresponds to the cancel ticket action. The candidate H61 is the specific handler for cancelling a ticket by orderId and loginId. Since the ticket has already been collected, the system will refuse the cancellation, but the request is still sent to this handler.",
        "services": [
          "ts-cancel-service",
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@59:74",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "R7;cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)@b49:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-cancel-service",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-cancel-service->ts-order-service:REST_HTTP",
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 10,
        "action": "Try to rebook the collected order onto the second high-speed trip found (the system refuses)",
        "edgeId": "ts-rebook-service->ts-common:REST_HTTP",
        "source": "ts-rebook-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/rebookservice/rebook",
        "relationType": "REST_HTTP",
        "handler": "method:ts-rebook-service:rebook.controller.RebookController#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "seatType": 2,
          "date": "2026-10-01"
        },
        "expectedOutcome": "refused",
        "reasoning": "The user attempts to rebook the collected order, which triggers the rebook service. Since the ticket has already been collected, the system refuses the operation. The correct handler for initiating a rebook is H174.",
        "services": [
          "ts-common",
          "ts-order-service",
          "ts-rebook-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R3:url_dispatch@393:79",
          "R3:url_dispatch@59:74",
          "R7:jackson_ctor",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service",
          "ts-rebook-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE",
          "ts-rebook-service->ts-order-service:REST_HTTP"
        ]
      },
      {
        "step": 11,
        "action": "Look up the luggage consignment of the order",
        "edgeId": "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE",
        "source": "ts-consign-service",
        "target": "ts-consign-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/consignservice/consigns/order/{id}",
        "relationType": "REST_HTTP",
        "handler": "method:ts-consign-service:consign.controller.ConsignController#findByOrderId(java.lang.String,org.springframework.http.HttpHeaders)",
        "params": {},
        "expectedOutcome": "success",
        "reasoning": "The step asks to look up the luggage consignment for the order, which corresponds to finding the consignment record by the order ID. Handler H76 is the specific endpoint for querying consignment by order ID and is marked as a UI action for this purpose.",
        "services": [
          "ts-consign-service"
        ],
        "tables": [
          "ts-consign-mysql.consign_record"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-consign-mysql-consign_record",
          "ts-consign-service"
        ],
        "activeEdges": [
          "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE"
        ]
      },
      {
        "step": 12,
        "action": "Change the consignee's name and phone number in the consignment",
        "edgeId": "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE",
        "source": "ts-consign-service",
        "target": "ts-consign-service",
        "httpMethod": "PUT",
        "endpoint": "/api/v1/consignservice/consigns",
        "relationType": "REST_HTTP",
        "handler": "method:ts-consign-service:consign.controller.ConsignController#updateConsign(consign.entity.Consign,org.springframework.http.HttpHeaders)",
        "params": {
          "isWithin": false
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to change the consignee's name and phone number in the consignment record associated with the order. Handler H79 (PUT /api/v1/consignservice/consigns) is the specific UI handler for updating a consignment record, which includes fields for consignee and phone. The consignment was looked up in step 11, so the request uses that consignment record.",
        "services": [
          "ts-consign-service"
        ],
        "tables": [
          "ts-consign-mysql.consign_record"
        ],
        "rules": [
          "ENTRY"
        ],
        "activeNodes": [
          "db-ts-consign-mysql-consign_record",
          "ts-consign-service"
        ],
        "activeEdges": [
          "ts-consign-service->db-ts-consign-mysql-consign_record:DATABASE"
        ]
      },
      {
        "step": 13,
        "action": "Refresh the list of orders filtered by travel date (September — December 2026)",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": true,
          "enableBoughtDateQuery": false,
          "travelDateStart": "2026-09-01",
          "travelDateEnd": "2026-12-31",
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders filtered by travel date. The scenario involves high-speed (GaoTie/DongChe) trains booked in step 2 and 4, which map to the base order service (ts-order-service). The UI action for refreshing orders with filters is handled by OrderController#queryOrdersForRefresh.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      },
      {
        "step": 14,
        "action": "Refresh the list of orders filtered by purchase date (today)",
        "edgeId": "ts-order-service->ts-common:REST_HTTP",
        "source": "ts-order-service",
        "target": "ts-common",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/refresh",
        "relationType": "REST_HTTP",
        "handler": "method:ts-order-service:order.controller.OrderController#queryOrdersForRefresh(order.entity.OrderInfo,org.springframework.http.HttpHeaders)",
        "params": {
          "enableStateQuery": false,
          "enableTravelDateQuery": false,
          "enableBoughtDateQuery": true,
          "travelDateStart": null,
          "travelDateEnd": null,
          "boughtDateStart": null,
          "boughtDateEnd": null
        },
        "expectedOutcome": "success",
        "reasoning": "The step asks to refresh the list of orders filtered by purchase date (today). Since the order was booked on a high-speed (G/D) train (step 2 and 4), the base order service (ts-order-service) handles G/D train orders. The UI action for refreshing orders with filters maps to the `queryOrdersForRefresh` endpoint in the order service.",
        "services": [
          "ts-common",
          "ts-order-service"
        ],
        "tables": [
          "ts-order-service.orders"
        ],
        "rules": [
          "ENTRY",
          "R7:read(m4 rows=yes)",
          "R7;ENTRY",
          "R7;R7:read(m4 rows=yes)",
          "order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)@b131:then"
        ],
        "activeNodes": [
          "db-ts-order-service-orders",
          "ts-common",
          "ts-order-service"
        ],
        "activeEdges": [
          "ts-order-service->db-ts-order-service-orders:DATABASE"
        ]
      }
    ]
  }
];
