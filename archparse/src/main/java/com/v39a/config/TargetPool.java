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

        return Collections.unmodifiableList(list);
    }
}
