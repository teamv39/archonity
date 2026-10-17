package com.v39a.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.List;

/**
 * Факты о сущностях JPA и вызовах репозиториев (data/entity_ir.json).
 * По ним движок решает, исполнился ли конструктор сущности при загрузке строк Hibernate (R7).
 */
public class EntityReportIR {

    @JsonProperty("schema")
    public String schema = "entity_ir/2";

    @JsonProperty("entities")
    public List<Entity> entities = new ArrayList<>();

    @JsonProperty("repository_calls")
    public List<RepositoryCall> repositoryCalls = new ArrayList<>();

    /** Число операторов в каждом явном конструкторе без аргументов: ID узла скелета -> число (0 — пустое тело). */
    @JsonProperty("no_arg_ctor_statements")
    public java.util.Map<String, Integer> noArgCtorStatements = new java.util.TreeMap<>();

    /** IR тел явных конструкторов без аргументов (вызовы, в том числе через enum-константы). */
    @JsonProperty("constructors")
    public List<MethodIR> constructors = new ArrayList<>();

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Entity {
        @JsonProperty("type")
        public String type;

        @JsonProperty("module")
        public String module;

        @JsonProperty("file")
        public String file;

        /** Entity, Embeddable или Document. */
        @JsonProperty("kind")
        public String kind;

        /** Имя основной таблицы: из @Table(name) или по правилу Spring (CamelCase -> snake_case). */
        @JsonProperty("table")
        public String table;

        @JsonProperty("id_field")
        public String idField;

        @JsonProperty("id_generated")
        public boolean idGenerated;

        /** ID узла скелета конструктора без аргументов; null, если конструктор не написан явно. */
        @JsonProperty("no_arg_ctor")
        public String noArgCtor;

        /** Число операторов в теле конструктора без аргументов (0 — пустое тело). */
        @JsonProperty("ctor_statements")
        public int ctorStatements;

        /** Конструктор без аргументов присваивает поле id. */
        @JsonProperty("ctor_assigns_id")
        public boolean ctorAssignsId;

        /** Типы полей @Embedded и полей-встраиваемых классов (их конструкторы Hibernate вызывает вместе с сущностью). */
        @JsonProperty("embedded")
        public List<String> embedded = new ArrayList<>();

        /** Коллекции, которые ORM хранит в отдельной таблице (@ElementCollection, @JoinTable). */
        @JsonProperty("collections")
        public List<CollectionField> collections = new ArrayList<>();
    }

    public static class CollectionField {
        @JsonProperty("field")
        public String field;

        /** Имя таблицы коллекции: @CollectionTable / @JoinTable(name) или «таблица сущности_поле». */
        @JsonProperty("table")
        public String table;

        /** LAZY (по умолчанию для коллекций) или EAGER. */
        @JsonProperty("fetch")
        public String fetch;
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class RepositoryCall {
        @JsonProperty("file")
        public String file;

        @JsonProperty("line")
        public int line;

        @JsonProperty("col")
        public int col;

        @JsonProperty("callee")
        public String callee;

        @JsonProperty("repository")
        public String repository;

        @JsonProperty("entity")
        public String entity;

        /** READ, SAVE, DELETE, EXISTS, COUNT, MODIFY (@Modifying @Query). */
        @JsonProperty("operation")
        public String operation;

        /** Чего ждёт успешный путь метода: ROWS, EMPTY или UNKNOWN. */
        @JsonProperty("expects")
        public String expects;

        /** Чем обосновано expects: строка условия и плечо с ошибкой. */
        @JsonProperty("expects_reason")
        public String expectsReason;

        /** Для SAVE: id сущности задан до вызова (Spring Data делает merge, Hibernate загружает строку). */
        @JsonProperty("id_assigned")
        public Boolean idAssigned;

        @JsonProperty("id_assigned_reason")
        public String idAssignedReason;

        /**
         * Для READ сущности с ленивыми коллекциями: поля коллекций, которые метод загружает сам, пока он на стеке
         * (результат геттера используется не только в return), в том числе в проектном методе, которому передана сущность.
         * Пустой список — метод коллекции не трогает, их загрузит сериализация ответа после возврата.
         */
        @JsonProperty("collections_loaded")
        public List<String> collectionsLoaded;

        @JsonProperty("collections_loaded_reason")
        public List<String> collectionsLoadedReason;
    }
}
