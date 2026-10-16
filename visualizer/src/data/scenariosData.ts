import type { RuntimeScenario } from "../types/graph";

export const TOPOLOGY_HUB_EXCLUSIONS = new Set<string>([
  "ts-eureka-service",
  "ts-eureka-auth-server",
  "ts-config-service",
  "rabbitmq",
  "zipkin",
  "ts-gateway-service"
]);

export const BENCHMARK_SCENARIOS: RuntimeScenario[] = [
  {
    "id": "Ticket_Preservation",
    "name": "Бронирование билетов (Ticket Preservation)",
    "description": "Комплексная цепочка проверки прав, бронирования мест, создания заказа, питания и страховки (13 шагов)",
    "steps": [
      {
        "step": 1,
        "edgeId": "ts-preserve-service->ts-security-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-security-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/securityservice/securityCheck",
        "relationType": "REST_HTTP",
        "action": "Проверка прав учетной записи и ограничений безопасности бронирования",
        "callerMethod": "preserve.service.PreserveServiceImpl.checkSecurity",
        "callChain": [
          "preserve.controller.PreserveController.preserve",
          "preserve.service.PreserveServiceImpl.preserve",
          "preserve.service.PreserveServiceImpl.checkSecurity"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-security-service\") + \"/api/v1/securityservice/securityCheck\", info, Response.class)"
      },
      {
        "step": 2,
        "edgeId": "ts-preserve-service->ts-travel-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-travel-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trips/left",
        "relationType": "REST_HTTP",
        "action": "Запрос доступности рейса и оставшихся свободных мест на маршруте",
        "callerMethod": "preserve.service.PreserveServiceImpl.queryTrip",
        "callChain": [
          "preserve.controller.PreserveController.preserve",
          "preserve.service.PreserveServiceImpl.preserve",
          "preserve.service.PreserveServiceImpl.queryTrip"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-travel-service\") + \"/api/v1/travelservice/trips/left\", info, Response.class)"
      },
      {
        "step": 3,
        "edgeId": "ts-travel-service->ts-ticketinfo-service:REST_HTTP",
        "source": "ts-travel-service",
        "target": "ts-ticketinfo-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/ticketinfoservice/ticketinfo",
        "relationType": "REST_HTTP",
        "action": "Каскадный запрос комплексной информации о билетах и деталях поездки",
        "callerMethod": "travel.service.TravelServiceImpl.getTicketInfo",
        "callChain": [
          "travel.controller.TravelController.queryInfo",
          "travel.service.TravelServiceImpl.queryInfo",
          "travel.service.TravelServiceImpl.getTicketInfo"
        ],
        "codeSnippet": "restTemplate.exchange(getServiceUrl(\"ts-ticketinfo-service\") + \"/api/v1/ticketinfoservice/ticketinfo\", HttpMethod.POST, requestEntity, new ParameterizedTypeReference<Response<TripAllDetail>>() {})"
      },
      {
        "step": 4,
        "edgeId": "ts-ticketinfo-service->ts-basic-service:REST_HTTP",
        "source": "ts-ticketinfo-service",
        "target": "ts-basic-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/basicservice/basic/travel",
        "relationType": "REST_HTTP",
        "action": "Агрегация базовой конфигурации поездки через сервисный фасад",
        "callerMethod": "ticketinfo.service.TicketInfoServiceImpl.queryForTravel",
        "callChain": [
          "ticketinfo.controller.TicketInfoController.queryForTravel",
          "ticketinfo.service.TicketInfoServiceImpl.queryForTravel"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-basic-service\") + \"/api/v1/basicservice/basic/travel\", travelInfo, Response.class)"
      },
      {
        "step": 5,
        "edgeId": "ts-basic-service->ts-station-service:REST_HTTP",
        "source": "ts-basic-service",
        "target": "ts-station-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/stationservice/stations/idlist",
        "relationType": "REST_HTTP",
        "action": "Пакетное разрешение наименований и идентификаторов станций маршрута",
        "callerMethod": "basic.service.BasicServiceImpl.queryStationList",
        "callChain": [
          "basic.controller.BasicController.queryForTravel",
          "basic.service.BasicServiceImpl.queryForTravel",
          "basic.service.BasicServiceImpl.queryStationList"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-station-service\") + \"/api/v1/stationservice/stations/idlist\", stationIdList, Response.class)"
      },
      {
        "step": 6,
        "edgeId": "ts-basic-service->ts-train-service:REST_HTTP",
        "source": "ts-basic-service",
        "target": "ts-train-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/trainservice/trains/byNames",
        "relationType": "REST_HTTP",
        "action": "Разрешение конфигураций вагонов и вместимости составов поездов по именам",
        "callerMethod": "basic.service.BasicServiceImpl.queryTrain",
        "callChain": [
          "basic.controller.BasicController.queryForTravel",
          "basic.service.BasicServiceImpl.queryForTravel",
          "basic.service.BasicServiceImpl.queryTrain"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-train-service\") + \"/api/v1/trainservice/trains/byNames\", trainNames, Response.class)"
      },
      {
        "step": 7,
        "edgeId": "ts-basic-service->ts-route-service:REST_HTTP",
        "source": "ts-basic-service",
        "target": "ts-route-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/routeservice/routes/{routeId}",
        "relationType": "REST_HTTP",
        "action": "Получение станционной структуры, остановок и расстояний маршрута по routeId",
        "callerMethod": "basic.service.BasicServiceImpl.getRouteById",
        "callChain": [
          "basic.controller.BasicController.queryForTravel",
          "basic.service.BasicServiceImpl.queryForTravel",
          "basic.service.BasicServiceImpl.getRouteById"
        ],
        "codeSnippet": "restTemplate.getForObject(getServiceUrl(\"ts-route-service\") + \"/api/v1/routeservice/routes/\" + routeId, Response.class)"
      },
      {
        "step": 8,
        "edgeId": "ts-basic-service->ts-price-service:REST_HTTP",
        "source": "ts-basic-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/priceservice/prices/byRouteIdsAndTrainTypes",
        "relationType": "REST_HTTP",
        "action": "Расчет базовой стоимости поездки по идентификаторам маршрута и типам поездов",
        "callerMethod": "basic.service.BasicServiceImpl.queryPrice",
        "callChain": [
          "basic.controller.BasicController.queryForTravel",
          "basic.service.BasicServiceImpl.queryForTravel",
          "basic.service.BasicServiceImpl.queryPrice"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-price-service\") + \"/api/v1/priceservice/prices/byRouteIdsAndTrainTypes\", query, Response.class)"
      },
      {
        "step": 9,
        "edgeId": "ts-preserve-service->ts-seat-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-seat-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/seatservice/seats",
        "relationType": "REST_HTTP",
        "action": "Резервирование и фиксация посадочного места пассажира в вагоне поезда",
        "callerMethod": "preserve.service.PreserveServiceImpl.distributeSeat",
        "callChain": [
          "preserve.controller.PreserveController.preserve",
          "preserve.service.PreserveServiceImpl.preserve",
          "preserve.service.PreserveServiceImpl.distributeSeat"
        ],
        "codeSnippet": "restTemplate.exchange(getServiceUrl(\"ts-seat-service\") + \"/api/v1/seatservice/seats\", HttpMethod.POST, requestEntity, new ParameterizedTypeReference<Response<Ticket>>() {})"
      },
      {
        "step": 10,
        "edgeId": "ts-preserve-service->ts-user-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-user-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/userservice/users/id/{userId}",
        "relationType": "REST_HTTP",
        "action": "Извлечение профиля пассажира, контактных данных и документов по userId",
        "callerMethod": "preserve.service.PreserveServiceImpl.findUserById",
        "callChain": [
          "preserve.controller.PreserveController.preserve",
          "preserve.service.PreserveServiceImpl.preserve",
          "preserve.service.PreserveServiceImpl.findUserById"
        ],
        "codeSnippet": "restTemplate.getForObject(getServiceUrl(\"ts-user-service\") + \"/api/v1/userservice/users/id/\" + accountId, Response.class)"
      },
      {
        "step": 11,
        "edgeId": "ts-preserve-service->ts-order-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-order-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order",
        "relationType": "REST_HTTP",
        "action": "Создание записи заказа в первичном статусе Создан/Не оплачен (OrderStatus.NOTPAID)",
        "callerMethod": "preserve.service.PreserveServiceImpl.createOrder",
        "callChain": [
          "preserve.controller.PreserveController.preserve",
          "preserve.service.PreserveServiceImpl.preserve",
          "preserve.service.PreserveServiceImpl.createOrder"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-order-service\") + \"/api/v1/orderservice/order\", orderInfo, Response.class)"
      },
      {
        "step": 12,
        "edgeId": "ts-preserve-service->ts-food-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-food-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/foodservice/orders",
        "relationType": "REST_HTTP",
        "action": "Оформление сопутствующего заказа бортового питания (дополнительная опция)",
        "callerMethod": "preserve.service.PreserveServiceImpl.preserveFood",
        "callChain": [
          "preserve.controller.PreserveController.preserve",
          "preserve.service.PreserveServiceImpl.preserve",
          "preserve.service.PreserveServiceImpl.preserveFood"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-food-service\") + \"/api/v1/foodservice/orders\", foodOrder, Response.class)"
      },
      {
        "step": 13,
        "edgeId": "ts-preserve-service->ts-consign-service:REST_HTTP",
        "source": "ts-preserve-service",
        "target": "ts-consign-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/consignservice/consigns",
        "relationType": "REST_HTTP",
        "action": "Оформление сопутствующего заказа перевозки багажа (дополнительная опция)",
        "callerMethod": "preserve.service.PreserveServiceImpl.consign",
        "callChain": [
          "preserve.controller.PreserveController.preserve",
          "preserve.service.PreserveServiceImpl.preserve",
          "preserve.service.PreserveServiceImpl.consign"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-consign-service\") + \"/api/v1/consignservice/consigns\", consign, Response.class)"
      }
    ]
  },
  {
    "id": "Inside_Payment",
    "name": "Внутренняя оплата и MQ (Inside Payment)",
    "description": "Цепочка проведения платежа: проверка баланса, изменение статуса заказа и отправка email в RabbitMQ",
    "steps": [
      {
        "step": 1,
        "edgeId": "ts-inside-payment-service->ts-payment-service:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-payment-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/paymentservice/payment",
        "relationType": "REST_HTTP",
        "action": "Вызов внешнего платежного адаптера для выполнения транзакции списания денежных средств",
        "callerMethod": "inside_payment.service.InsidePaymentServiceImpl.payDifference",
        "callChain": [
          "inside_payment.controller.InsidePaymentController.pay",
          "inside_payment.service.InsidePaymentServiceImpl.pay",
          "inside_payment.service.InsidePaymentServiceImpl.payDifference"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-payment-service\") + \"/api/v1/paymentservice/payment\", paymentInfo, Response.class)"
      },
      {
        "step": 2,
        "edgeId": "ts-inside-payment-service->ts-order-service:REST_HTTP",
        "source": "ts-inside-payment-service",
        "target": "ts-order-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/status",
        "relationType": "REST_HTTP",
        "action": "Обновление жизненного цикла заказа в статус Оплачен (OrderStatus.PAID)",
        "callerMethod": "inside_payment.service.InsidePaymentServiceImpl.modifyOrderStatus",
        "callChain": [
          "inside_payment.controller.InsidePaymentController.pay",
          "inside_payment.service.InsidePaymentServiceImpl.pay",
          "inside_payment.service.InsidePaymentServiceImpl.modifyOrderStatus"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-order-service\") + \"/api/v1/orderservice/order/status\", orderStatusInfo, Response.class)"
      },
      {
        "step": 3,
        "edgeId": "ts-inside-payment-service->rabbitmq:MESSAGE_QUEUE",
        "source": "ts-inside-payment-service",
        "target": "rabbitmq",
        "httpMethod": null,
        "endpoint": "email",
        "relationType": "MESSAGE_QUEUE",
        "action": "Прямая асинхронная публикация почтового уведомления об успешной оплате из сервиса оплаты в очередь RabbitMQ email",
        "callerMethod": "inside_payment.service.InsidePaymentServiceImpl.notifyPayment",
        "callChain": [
          "inside_payment.controller.InsidePaymentController.pay",
          "inside_payment.service.InsidePaymentServiceImpl.pay",
          "inside_payment.service.InsidePaymentServiceImpl.notifyPayment"
        ],
        "codeSnippet": "rabbitTemplate.convertAndSend(\"email\", paymentNotification)"
      },
      {
        "step": 4,
        "edgeId": "ts-order-service->rabbitmq:MESSAGE_QUEUE",
        "source": "ts-order-service",
        "target": "rabbitmq",
        "httpMethod": null,
        "endpoint": "email",
        "relationType": "MESSAGE_QUEUE",
        "action": "Транзакционная публикация события изменения статуса оплаченного заказа в очередь RabbitMQ email",
        "callerMethod": "order.service.OrderServiceImpl.initNotification",
        "callChain": [
          "order.controller.OrderController.modifyOrderStatus",
          "order.service.OrderServiceImpl.modifyOrder",
          "order.service.OrderServiceImpl.initNotification"
        ],
        "codeSnippet": "rabbitTemplate.convertAndSend(\"email\", orderNotification)"
      },
      {
        "step": 5,
        "edgeId": "rabbitmq->ts-notification-service:MESSAGE_QUEUE",
        "source": "rabbitmq",
        "target": "ts-notification-service",
        "httpMethod": null,
        "endpoint": "email",
        "relationType": "MESSAGE_QUEUE",
        "action": "Потребление события уведомления из очереди RabbitMQ email слушателем @RabbitListener для генерации почтового квитка",
        "callerMethod": "notification.mq.RabbitReceive.process",
        "callChain": [
          "notification.mq.RabbitReceive.process"
        ],
        "codeSnippet": "@RabbitListener(queues = \"email\") public void process(Notification notification)"
      },
      {
        "step": 6,
        "edgeId": "ts-inside-payment-service->ts-notification-service:MESSAGE_QUEUE",
        "source": "ts-inside-payment-service",
        "target": "ts-notification-service",
        "httpMethod": null,
        "endpoint": "email",
        "relationType": "MESSAGE_QUEUE",
        "action": "Прямая логическая асинхронная связь между сервисом оплаты и сервисом нотификаций через очередь email (для графов без промежуточного узла брокера)"
      },
      {
        "step": 7,
        "edgeId": "ts-order-service->ts-notification-service:MESSAGE_QUEUE",
        "source": "ts-order-service",
        "target": "ts-notification-service",
        "httpMethod": null,
        "endpoint": "email",
        "relationType": "MESSAGE_QUEUE",
        "action": "Прямая логическая асинхронная связь между сервисом заказов и сервисом нотификаций через очередь email (для графов без промежуточного узла брокера)"
      }
    ]
  },
  {
    "id": "Ticket_Cancellation",
    "name": "Отмена заказа и возврат (Ticket Cancellation)",
    "description": "Отмена купленного билета: обновление статуса заказа, возврат средств и освобождение мест",
    "steps": [
      {
        "step": 1,
        "edgeId": "ts-cancel-service->ts-order-service:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-order-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/orderservice/order/{orderId}",
        "relationType": "REST_HTTP",
        "action": "Запрос метаданных, реквизитов и стоимости билета отменяемого заказа по orderId",
        "callerMethod": "cancel.service.CancelServiceImpl.getOrderById",
        "callChain": [
          "cancel.controller.CancelController.cancelTicket",
          "cancel.service.CancelServiceImpl.cancelOrder",
          "cancel.service.CancelServiceImpl.getOrderById"
        ],
        "codeSnippet": "restTemplate.getForObject(getServiceUrl(\"ts-order-service\") + \"/api/v1/orderservice/order/\" + orderId, Response.class)"
      },
      {
        "step": 2,
        "edgeId": "ts-cancel-service->ts-inside-payment-service:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-inside-payment-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/inside_pay_service/inside_payment/refund",
        "relationType": "REST_HTTP",
        "action": "Инициация транзакции возврата средств пассажиру с расчетом и удержанием штрафа (комиссии)",
        "callerMethod": "cancel.service.CancelServiceImpl.drawBack",
        "callChain": [
          "cancel.controller.CancelController.cancelTicket",
          "cancel.service.CancelServiceImpl.cancelOrder",
          "cancel.service.CancelServiceImpl.drawBack"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-inside-payment-service\") + \"/api/v1/inside_pay_service/inside_payment/refund\", refundInfo, Response.class)"
      },
      {
        "step": 3,
        "edgeId": "ts-cancel-service->ts-order-service:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-order-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/orderservice/order/status",
        "relationType": "REST_HTTP",
        "action": "Обновление жизненного цикла заказа на статус Отменен (OrderStatus.CANCEL)",
        "callerMethod": "cancel.service.CancelServiceImpl.changeOrderStatus",
        "callChain": [
          "cancel.controller.CancelController.cancelTicket",
          "cancel.service.CancelServiceImpl.cancelOrder",
          "cancel.service.CancelServiceImpl.changeOrderStatus"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-order-service\") + \"/api/v1/orderservice/order/status\", statusInfo, Response.class)"
      },
      {
        "step": 4,
        "edgeId": "ts-cancel-service->ts-seat-service:REST_HTTP",
        "source": "ts-cancel-service",
        "target": "ts-seat-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/seatservice/seats",
        "relationType": "REST_HTTP",
        "action": "Разблокировка и возвращение ранее закрепленного посадочного места в пул доступных для повторной продажи",
        "callerMethod": "cancel.service.CancelServiceImpl.modifySeatStatus",
        "callChain": [
          "cancel.controller.CancelController.cancelTicket",
          "cancel.service.CancelServiceImpl.cancelOrder",
          "cancel.service.CancelServiceImpl.modifySeatStatus"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-seat-service\") + \"/api/v1/seatservice/seats\", seatInfo, Response.class)"
      }
    ]
  },
  {
    "id": "Travel_Route_Planning",
    "name": "Поиск и планирование маршрута (Route Planning)",
    "description": "Поиск оптимального маршрута, проверка станций, расчет стоимости и времени в пути",
    "steps": [
      {
        "step": 1,
        "edgeId": "ts-route-plan-service->ts-route-service:REST_HTTP",
        "source": "ts-route-plan-service",
        "target": "ts-route-service",
        "httpMethod": "GET",
        "endpoint": "/api/v1/routeservice/routes",
        "relationType": "REST_HTTP",
        "action": "Получение топологического графа железнодорожных станций и доступных линий сообщения",
        "callerMethod": "routeplan.service.RoutePlanServiceImpl.getRoutes",
        "callChain": [
          "routeplan.controller.RoutePlanController.getCheapestRoutes",
          "routeplan.service.RoutePlanServiceImpl.searchCheapestResult",
          "routeplan.service.RoutePlanServiceImpl.getRoutes"
        ],
        "codeSnippet": "restTemplate.getForObject(getServiceUrl(\"ts-route-service\") + \"/api/v1/routeservice/routes\", Response.class)"
      },
      {
        "step": 2,
        "edgeId": "ts-route-plan-service->ts-travel-service:REST_HTTP",
        "source": "ts-route-plan-service",
        "target": "ts-travel-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/travelservice/trips/routes",
        "relationType": "REST_HTTP",
        "action": "Пакетный запрос расписаний и доступных рейсов по сегментам планируемого маршрута",
        "callerMethod": "routeplan.service.RoutePlanServiceImpl.getTripsByRoute",
        "callChain": [
          "routeplan.controller.RoutePlanController.getCheapestRoutes",
          "routeplan.service.RoutePlanServiceImpl.searchCheapestResult",
          "routeplan.service.RoutePlanServiceImpl.getTripsByRoute"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-travel-service\") + \"/api/v1/travelservice/trips/routes\", routeIds, Response.class)"
      },
      {
        "step": 3,
        "edgeId": "ts-route-plan-service->ts-price-service:REST_HTTP",
        "source": "ts-route-plan-service",
        "target": "ts-price-service",
        "httpMethod": "POST",
        "endpoint": "/api/v1/priceservice/prices/byRouteIdsAndTrainTypes",
        "relationType": "REST_HTTP",
        "action": "Расчет и сопоставление суммарной стоимости альтернативных маршрутных цепочек для выбора оптимума",
        "callerMethod": "routeplan.service.RoutePlanServiceImpl.queryPrice",
        "callChain": [
          "routeplan.controller.RoutePlanController.getCheapestRoutes",
          "routeplan.service.RoutePlanServiceImpl.searchCheapestResult",
          "routeplan.service.RoutePlanServiceImpl.queryPrice"
        ],
        "codeSnippet": "restTemplate.postForObject(getServiceUrl(\"ts-price-service\") + \"/api/v1/priceservice/prices/byRouteIdsAndTrainTypes\", priceQuery, Response.class)"
      }
    ]
  }
];
