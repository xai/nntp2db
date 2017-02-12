-- MySQL Workbench Forward Engineering

SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='TRADITIONAL,ALLOW_INVALID_DATES';

-- -----------------------------------------------------
-- Schema mailinglists
-- -----------------------------------------------------

-- -----------------------------------------------------
-- Schema mailinglists
-- -----------------------------------------------------
CREATE SCHEMA IF NOT EXISTS `mailinglists` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci ;
USE `mailinglists` ;

-- -----------------------------------------------------
-- Table `mailinglists`.`list`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `mailinglists`.`list` ;

CREATE TABLE IF NOT EXISTS `mailinglists`.`list` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '',
  `name` VARCHAR(45) NOT NULL COMMENT '',
  PRIMARY KEY (`id`)  COMMENT '',
  UNIQUE INDEX `id_UNIQUE` (`id` ASC)  COMMENT '',
  UNIQUE INDEX `name_UNIQUE` (`name` ASC)  COMMENT '')
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `mailinglists`.`person`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `mailinglists`.`person` ;

CREATE TABLE IF NOT EXISTS `mailinglists`.`person` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '',
  `name` VARCHAR(255) NULL COMMENT '',
  `address` VARCHAR(255) NULL COMMENT '',
  PRIMARY KEY (`id`)  COMMENT '',
  UNIQUE INDEX `id_UNIQUE` (`id` ASC)  COMMENT '',
  UNIQUE INDEX `name_address` (`name` ASC, `address` ASC)  COMMENT '')
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `mailinglists`.`mail`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `mailinglists`.`mail` ;

CREATE TABLE IF NOT EXISTS `mailinglists`.`mail` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '',
  `message_id` VARCHAR(255) NOT NULL COMMENT '',
  `subject` VARCHAR(1023) NOT NULL COMMENT '',
  `date` DATETIME NOT NULL COMMENT '',
  `timezone` VARCHAR(45) NULL DEFAULT '+0000' COMMENT '',
  `from` INT UNSIGNED NOT NULL COMMENT '',
  `lines` INT UNSIGNED NULL COMMENT '',
  `header` MEDIUMTEXT NOT NULL COMMENT '',
  `content` LONGTEXT NULL COMMENT '',
  PRIMARY KEY (`id`)  COMMENT '',
  UNIQUE INDEX `id_UNIQUE` (`id` ASC)  COMMENT '',
  INDEX `fk_mails_1_idx` (`from` ASC)  COMMENT '',
  CONSTRAINT `fk_mails_1`
    FOREIGN KEY (`from`)
    REFERENCES `mailinglists`.`person` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `mailinglists`.`mbox`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `mailinglists`.`mbox` ;

CREATE TABLE IF NOT EXISTS `mailinglists`.`mbox` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '',
  `list` INT UNSIGNED NOT NULL COMMENT '',
  `mail` INT UNSIGNED NOT NULL COMMENT '',
  INDEX `fk_mboxes_2_idx` (`mail` ASC)  COMMENT '',
  PRIMARY KEY (`id`)  COMMENT '',
  CONSTRAINT `fk_mboxes_1`
    FOREIGN KEY (`list`)
    REFERENCES `mailinglists`.`list` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_mboxes_2`
    FOREIGN KEY (`mail`)
    REFERENCES `mailinglists`.`mail` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `mailinglists`.`recipient`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `mailinglists`.`recipient` ;

CREATE TABLE IF NOT EXISTS `mailinglists`.`recipient` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '',
  `mail` INT UNSIGNED NOT NULL COMMENT '',
  `recipient` INT UNSIGNED NOT NULL COMMENT '',
  `to` TINYINT(1) NOT NULL COMMENT '',
  `cc` TINYINT(1) NOT NULL COMMENT '',
  PRIMARY KEY (`id`)  COMMENT '',
  UNIQUE INDEX `id_UNIQUE` (`id` ASC)  COMMENT '',
  INDEX `fk_recipients_1_idx` (`mail` ASC)  COMMENT '',
  INDEX `fk_recipients_2_idx` (`recipient` ASC)  COMMENT '',
  CONSTRAINT `fk_recipients_1`
    FOREIGN KEY (`mail`)
    REFERENCES `mailinglists`.`mail` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_recipients_2`
    FOREIGN KEY (`recipient`)
    REFERENCES `mailinglists`.`person` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `mailinglists`.`reference`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `mailinglists`.`reference` ;

CREATE TABLE IF NOT EXISTS `mailinglists`.`reference` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '',
  `from` INT UNSIGNED NOT NULL COMMENT '',
  `to` INT UNSIGNED NULL COMMENT '',
  `to_message_id` VARCHAR(255) NULL COMMENT '',
  PRIMARY KEY (`id`)  COMMENT '',
  INDEX `fk_reference_1_idx` (`from` ASC)  COMMENT '',
  INDEX `fk_reference_2_idx` (`to` ASC)  COMMENT '',
  CONSTRAINT `fk_reference_1`
    FOREIGN KEY (`from`)
    REFERENCES `mailinglists`.`mail` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_reference_2`
    FOREIGN KEY (`to`)
    REFERENCES `mailinglists`.`mail` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `mailinglists`.`in_reply_to`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `mailinglists`.`in_reply_to` ;

CREATE TABLE IF NOT EXISTS `mailinglists`.`in_reply_to` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '',
  `mail` INT UNSIGNED NOT NULL COMMENT '',
  `replyto` INT UNSIGNED NULL COMMENT '',
  `replyto_message_id` VARCHAR(255) NULL COMMENT '',
  PRIMARY KEY (`id`)  COMMENT '',
  INDEX `fk_reference_1_idx` (`mail` ASC)  COMMENT '',
  INDEX `fk_reference_2_idx` (`replyto` ASC)  COMMENT '',
  CONSTRAINT `fk_reference_10`
    FOREIGN KEY (`mail`)
    REFERENCES `mailinglists`.`mail` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION,
  CONSTRAINT `fk_reference_20`
    FOREIGN KEY (`replyto`)
    REFERENCES `mailinglists`.`mail` (`id`)
    ON DELETE NO ACTION
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;