package com.v39a.config;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class TargetPool {

    public static List<TargetMethod> getInitialPool() {
        List<TargetMethod> list = new ArrayList<>();

        // 1. CancelServiceImpl
        String cancelFile = "ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
                cancelFile, "cancelOrder", "String", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-cancel-service:cancel.service.CancelServiceImpl#calculateRefund(java.lang.String,org.springframework.http.HttpHeaders)",
                cancelFile, "calculateRefund", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-cancel-service:cancel.service.CancelServiceImpl#calculateRefund(edu.fudan.common.entity.Order)",
                cancelFile, "calculateRefund", "Order"
        ));

        // 2. ExecuteServiceImpl
        String execFile = "ts-execute-service/src/main/java/execute/serivce/ExecuteServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-execute-service:execute.serivce.ExecuteServiceImpl#ticketExecute(java.lang.String,org.springframework.http.HttpHeaders)",
                execFile, "ticketExecute", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-execute-service:execute.serivce.ExecuteServiceImpl#ticketCollect(java.lang.String,org.springframework.http.HttpHeaders)",
                execFile, "ticketCollect", "String", "HttpHeaders"
        ));

        // 3. InsidePaymentServiceImpl
        String payFile = "ts-inside-payment-service/src/main/java/inside_payment/service/InsidePaymentServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-inside-payment-service:inside_payment.service.InsidePaymentServiceImpl#pay(inside_payment.entity.PaymentInfo,org.springframework.http.HttpHeaders)",
                payFile, "pay", "PaymentInfo", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-inside-payment-service:inside_payment.service.InsidePaymentServiceImpl#setOrderStatus(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
                payFile, "setOrderStatus", "String", "String", "HttpHeaders"
        ));

        // 4. RebookServiceImpl
        String rebookFile = "ts-rebook-service/src/main/java/rebook/service/RebookServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-rebook-service:rebook.service.RebookServiceImpl#rebook(rebook.entity.RebookInfo,org.springframework.http.HttpHeaders)",
                rebookFile, "rebook", "RebookInfo", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-rebook-service:rebook.service.RebookServiceImpl#updateOrder(edu.fudan.common.entity.Order,java.lang.String,org.springframework.http.HttpHeaders)",
                rebookFile, "updateOrder", "Order", "String", "HttpHeaders"
        ));

        return Collections.unmodifiableList(list);
    }

    public static List<TargetMethod> getFullPool() {
        List<TargetMethod> list = new ArrayList<>(getInitialPool());

        // 5. PreserveServiceImpl & PreserveOtherServiceImpl
        String preserveFile = "ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-preserve-service:preserve.service.PreserveServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
                preserveFile, "preserve", "OrderTicketsInfo", "HttpHeaders"
        ));

        String preserveOtherFile = "ts-preserve-other-service/src/main/java/preserveOther/service/PreserveOtherServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-preserve-other-service:preserveOther.service.PreserveOtherServiceImpl#preserve(edu.fudan.common.entity.OrderTicketsInfo,org.springframework.http.HttpHeaders)",
                preserveOtherFile, "preserve", "OrderTicketsInfo", "HttpHeaders"
        ));

        // 6. ConsignServiceImpl
        String consignFile = "ts-consign-service/src/main/java/consign/service/ConsignServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-consign-service:consign.service.ConsignServiceImpl#updateConsignRecord(consign.entity.Consign,org.springframework.http.HttpHeaders)",
                consignFile, "updateConsignRecord", "Consign", "HttpHeaders"
        ));

        // 7. OrderServiceImpl & OrderOtherServiceImpl
        String orderFile = "ts-order-service/src/main/java/order/service/OrderServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-order-service:order.service.OrderServiceImpl#queryOrders(order.entity.OrderInfo,java.lang.String,org.springframework.http.HttpHeaders)",
                orderFile, "queryOrders", "OrderInfo", "String", "HttpHeaders"
        ));
        String orderOtherFile = "ts-order-other-service/src/main/java/other/service/OrderOtherServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-order-other-service:other.service.OrderOtherServiceImpl#queryOrders(other.entity.QueryInfo,java.lang.String,org.springframework.http.HttpHeaders)",
                orderOtherFile, "queryOrders", "QueryInfo", "String", "HttpHeaders"
        ));

        // 8. TokenServiceImpl (ts-auth-service)
        String tokenFile = "ts-auth-service/src/main/java/auth/service/impl/TokenServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-auth-service:auth.service.impl.TokenServiceImpl#getToken(auth.dto.BasicAuthDto,org.springframework.http.HttpHeaders)",
                tokenFile, "getToken", "BasicAuthDto", "HttpHeaders"
        ));

        // 9. UserServiceImpl (ts-user-service)
        String userFile = "ts-user-service/src/main/java/user/service/impl/UserServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-user-service:user.service.impl.UserServiceImpl#saveUser(user.dto.UserDto,?HttpHeaders)",
                userFile, "saveUser", "UserDto", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-user-service:user.service.impl.UserServiceImpl#createDefaultAuthUser(user.dto.AuthDto)",
                userFile, "createDefaultAuthUser", "AuthDto"
        ));
        // 10. AdminOrderServiceImpl (ts-admin-order-service)
        String adminOrderFile = "ts-admin-order-service/src/main/java/adminorder/service/AdminOrderServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-admin-order-service:adminorder.service.AdminOrderServiceImpl#getAllOrders(org.springframework.http.HttpHeaders)",
                adminOrderFile, "getAllOrders", "HttpHeaders"
        ));

        // 11. Методы с enum-вызовами R7 вне основных сценарных обработчиков
        String cancelFile = "ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java";
        list.add(new TargetMethod(
                "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelFromOrder(edu.fudan.common.entity.Order,org.springframework.http.HttpHeaders)",
                cancelFile, "cancelFromOrder", "Order", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-cancel-service:cancel.service.CancelServiceImpl#cancelFromOtherOrder(edu.fudan.common.entity.Order,org.springframework.http.HttpHeaders)",
                cancelFile, "cancelFromOtherOrder", "Order", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-rebook-service:rebook.service.RebookServiceImpl#updateOrder(edu.fudan.common.entity.Order,rebook.entity.RebookInfo,edu.fudan.common.entity.TripAllDetail,java.lang.String,org.springframework.http.HttpHeaders)",
                "ts-rebook-service/src/main/java/rebook/service/RebookServiceImpl.java",
                "updateOrder", "Order", "RebookInfo", "TripAllDetail", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-order-service:order.service.OrderServiceImpl#alterOrder(order.entity.OrderAlterInfo,org.springframework.http.HttpHeaders)",
                orderFile, "alterOrder", "OrderAlterInfo", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-order-service:order.service.OrderServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
                orderFile, "cancelOrder", "String", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-order-service:order.service.OrderServiceImpl#payOrder(java.lang.String,org.springframework.http.HttpHeaders)",
                orderFile, "payOrder", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-order-other-service:other.service.OrderOtherServiceImpl#alterOrder(other.entity.OrderAlterInfo,org.springframework.http.HttpHeaders)",
                orderOtherFile, "alterOrder", "OrderAlterInfo", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-order-other-service:other.service.OrderOtherServiceImpl#cancelOrder(java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
                orderOtherFile, "cancelOrder", "String", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-order-other-service:other.service.OrderOtherServiceImpl#payOrder(java.lang.String,org.springframework.http.HttpHeaders)",
                orderOtherFile, "payOrder", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-travel-service:travel.service.TravelServiceImpl#setResponse(travel.entity.Trip,edu.fudan.common.entity.TravelResult,java.lang.String,java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
                "ts-travel-service/src/main/java/travel/service/TravelServiceImpl.java",
                "setResponse", "Trip", "TravelResult", "String", "String", "String", "HttpHeaders"
        ));
        list.add(new TargetMethod(
                "method:ts-travel2-service:travel2.service.TravelServiceImpl#setResponse(travel2.entity.Trip,edu.fudan.common.entity.TravelResult,java.lang.String,java.lang.String,java.lang.String,org.springframework.http.HttpHeaders)",
                "ts-travel2-service/src/main/java/travel2/service/TravelServiceImpl.java",
                "setResponse", "Trip", "TravelResult", "String", "String", "String", "HttpHeaders"
        ));
        String planFile = "ts-travel-plan-service/src/main/java/travelplan/service/TravelPlanServiceImpl.java";
        for (String name : new String[]{"getCheapest", "getQuickest", "getMinStation"}) {
            list.add(new TargetMethod(
                    "method:ts-travel-plan-service:travelplan.service.TravelPlanServiceImpl#" + name
                            + "(edu.fudan.common.entity.TripInfo,org.springframework.http.HttpHeaders)",
                    planFile, name, "TripInfo", "HttpHeaders"
            ));
        }

        return Collections.unmodifiableList(list);
    }
}
